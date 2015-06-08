# Copyright 2011-2012 James McCauley
# Copyright 2014-2015 Vamshi Reddy
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
An L2 learning switch module which can detect ARP spoofing attacks in the Software defined networks.
"""

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.util import dpid_to_str
from pox.lib.util import str_to_bool
import pox.lib.packet as pkt
import time
import datetime
import threading
from threading import Lock
from pox.lib.addresses import IPAddr, IPAddr6, EthAddr

# Global Hosts IP, MAC hash table 
# key: HostIP 
# Value: MAC
# This keeps track of the IP addresses leased by the DHCP server
hosts = {}

log = core.getLogger()

# We don't want to flood immediately when a switch connects.
# Can be overriden on commandline.
_flood_delay = 0

class ARPSpoofDetection (object):
	"""
		This class implements the ARP spoofing detection and mitigation mechanisms.
	"""
	@staticmethod
	def IsSpoofedPacket(packet):
		
		"""
			Input: Packet
			Output: True --> Spoofing detected
					False --> No Spoofing
			This function analyzes the packet and detects if the packet is a spoofed packet
		"""
		# If ARP packet, then check if the packet is spoofed. If spoof, install entry to drop packets and return
		# If its not, then continue with the flow.
		if packet.type == packet.ARP_TYPE:
			# Its ARP packet
			# Copy the src, dst MAC from ethernet headers
			src_mac_eth = str(packet.src)
			dst_mac_eth = str(packet.dst)
			# Copy the src, dst IP and src MAC from the ARP header
			src_ip_arp = str(packet.payload.protosrc)
			src_mac_arp = str(packet.payload.hwsrc) 
			dst_ip_arp = str(packet.payload.protodst)
			dst_mac_arp = str(packet.payload.hwdst)
			
			if packet.payload.opcode == pkt.arp.REQUEST:
				# Its request packet
				print "Its ARP request\n"
				print "Spoof detected\n"
				print "Src MAC: "+src_mac_eth+"\n"
				print "Src MAC ARP: "+src_mac_arp+"\n"
				print "Dst MAC: "+dst_mac_eth+"\n"
				print "Dst MAC ARP: "+dst_mac_arp+"\n"
				print "Src IP ARP: "+src_ip_arp+"\n"
				print "Dst IP ARP: "+dst_ip_arp+"\n"
				if src_mac_eth != src_mac_arp or (hosts[src_ip_arp] != src_mac_arp) or (dst_ip_arp not in hosts.keys()):
					return True
				
			elif packet.payload.opcode == pkt.arp.REPLY:
				# Its reply packet
				print "Its ARP reply"
				if (src_mac_eth != src_mac_arp) or (dst_mac_eth != dst_mac_arp) or (hosts[src_ip_arp] != src_mac_arp) or (hosts[dst_ip_arp] != dst_mac_arp) or (dst_mac_eth == "ff:ff:ff:ff:ff:ff") :
					# Spoofing detected.
					return True
		return False

	@staticmethod
	def handleSpoofing(event, packet, mac=None):
		"""
		Function which is called when the ARP spoofing is detected. 
		This will install a flow entry to drop the packets coming from a port to filter out the malicious packets
		"""
		actions = []
		actions.append(of.ofp_action_output(port = of.OFPP_NONE)) # Drop
		msg = of.ofp_flow_mod(command=of.OFPFC_ADD,
                                idle_timeout = 10, # Drop packets for 10 idle seconds
                                hard_timeout = 60, # Drop packets for 60 seconds
                                buffer_id=event.ofp.buffer_id,
                                actions=actions,
                                match=of.ofp_match.from_packet(packet,
                                                               event.port))
		event.connection.send(msg.pack())
		print "Installed an entry to drop all the packets from the port"
		log.debug("installing flow for %s.%i -> %s to DROP" % (packet.src, event.port, packet.dst))
		

class LearningSwitch (object):
	"""
	The learning switch "brain" associated with a single OpenFlow switch.
	When we see a packet, we'd like to output it on a port which will
	eventually lead to the destination.  To accomplish this, we build a
	table that maps addresses to ports.
	
	We populate the table by observing traffic.  When we see a packet
	from some source coming from some port, we know that source is out
	that port.
	
	When we want to forward traffic, we look up the desintation in our
	table.  If we don't know the port, we simply send the message out
	all ports except the one it came in on.  (In the presence of loops,
	this is bad!).
	
	In short, our algorithm looks like this:
	
	For each packet from the switch:
	1) Use source address and switch port to update address/port table
	2) Is transparent = False and either Ethertype is LLDP or the packet's
	 destination address is a Bridge Filtered address?
	 Yes:
		2a) Drop packet -- don't forward link-local traffic (LLDP, 802.1x)
			DONE
	3) Is destination multicast?
	 Yes:
		3a) Flood the packet
			DONE
	4) Port for destination address in our address/port table?
	 No:
		4a) Flood the packet
			DONE
	5) Is output port the same as input port?
	 Yes:
		5a) Drop packet and similar ones for a while
	6) Install flow table entry in the switch so that this
	 flow goes out the appopriate port
	 6a) Send the packet out appropriate port
	"""
	def _handle_dhcp_lease(self, event):
		"""
		DHCP lease event handler. It is a callback function, which is invoked whenever the DHCP server leases an IP address to a host
		"""
		# Add the current IP and MAC to the hash table ( hosts )
		if event.ip != None and event.host_mac != None :
			hosts[str(event.ip)] = str(event.host_mac)
	
	def __init__ (self, connection, transparent):
    
		# Switch we'll be adding L2 learning switch capabilities to
		self.connection = connection
		self.transparent = transparent

		# Our Switch table
		self.macToPort = {}

		# We want to hear PacketIn messages, so we listen
		# to the connection
		connection.addListeners(self)
		
		# We just use this to know when to log a helpful message
		self.hold_down_expired = _flood_delay == 0
		
		log.debug("Initializing LearningSwitch, transparent=%s",
				  str(self.transparent))
		
		# Now add entries to the switch for capturing ARP traffic at the controller.
		# This will send all ARP packets to the controller.
		msg = of.ofp_flow_mod()
		msg.match = of.ofp_match(dl_type = pkt.ethernet.ARP_TYPE);
		msg.idle_timeout = of.OFP_FLOW_PERMANENT;
		msg.hard_timeout = of.OFP_FLOW_PERMANENT;
		msg.actions.append(of.ofp_action_output(port = of.OFPP_CONTROLLER))
		self.connection.send(msg)
		
		# Add flow entries to capture DHCP packets at the controller.
		# Send all DHCP packets to the controller.
		msg = of.ofp_flow_mod()
		msg.match = of.ofp_match(nw_proto = 17, tp_src = 67 , tp_dst = 68 );
		msg.idle_timeout = of.OFP_FLOW_PERMANENT;
		msg.hard_timeout = of.OFP_FLOW_PERMANENT;
		msg.actions.append(of.ofp_action_output(port = of.OFPP_CONTROLLER))
		
		# Register a handler for DHCP IP lease at the controller.
		# This is called when DHCP lease is given by the controller DHCP server.
		core.DHCPD.addListenerByName('DHCPLease',self._handle_dhcp_lease)

	def _handle_PacketIn (self, event):
		"""
		Handle packet in messages from the switch to implement above algorithm.
		"""
		packet = event.parsed

		def flood (message = None):
			""" Floods the packet """
			msg = of.ofp_packet_out()
			if time.time() - self.connection.connect_time >= _flood_delay:
				# Only flood if we've been connected for a little while...
				if self.hold_down_expired is False:
					# Oh yes it is!
					self.hold_down_expired = True
					log.info("%s: Flood hold-down expired -- flooding", dpid_to_str(event.dpid))

				if message is not None: log.debug(message)
				#log.debug("%i: flood %s -> %s", event.dpid,packet.src,packet.dst)
				# OFPP_FLOOD is optional; on some switches you may need to change
				# this to OFPP_ALL.
				msg.actions.append(of.ofp_action_output(port = of.OFPP_FLOOD))
			else:
				pass
				#log.info("Holding down flood for %s", dpid_to_str(event.dpid))
			msg.data = event.ofp
			msg.in_port = event.port
			self.connection.send(msg)

		def drop (duration = None):
			"""
			Drops this packet and optionally installs a flow to continue
			dropping similar ones for a while
			"""
			if duration is not None:
				if not isinstance(duration, tuple):
					duration = (duration,duration)
				msg = of.ofp_flow_mod()
				msg.match = of.ofp_match.from_packet(packet)
				msg.idle_timeout = duration[0]
				msg.hard_timeout = duration[1]
				msg.buffer_id = event.ofp.buffer_id
				self.connection.send(msg)
			elif event.ofp.buffer_id is not None:
				msg = of.ofp_packet_out()
				msg.buffer_id = event.ofp.buffer_id
				msg.in_port = event.port
				self.connection.send(msg)

		# Check ARP Spoofing
		if ARPSpoofDetection.IsSpoofedPacket(packet) :
			# Spoofing detected
			print "*******************SPOOFING DETECTED**********************\n"
			ARPSpoofDetection.handleSpoofing(event, packet)
			# Done with this ARP packet
			return

		
		# Valid packet, do processing.
		self.macToPort[packet.src] = event.port # 1
		if not self.transparent: # 2
			if packet.type == packet.LLDP_TYPE or packet.dst.isBridgeFiltered():
				drop() # 2a
				return
		if packet.dst.is_multicast:
		  flood() # 3a
		else:
		  if packet.dst not in self.macToPort: # 4
			flood("Port for %s unknown -- flooding" % (packet.dst,)) # 4a
		  else:
			port = self.macToPort[packet.dst]
			if port == event.port: # 5
			  # 5a
			  log.warning("Same port for packet from %s -> %s on %s.%s.  Drop."
				  % (packet.src, packet.dst, dpid_to_str(event.dpid), port))
			  drop(10)
			  return
			# 6
			log.debug("installing flow for %s.%i -> %s.%i" %
					  (packet.src, event.port, packet.dst, port))
			msg = of.ofp_flow_mod()
			msg.match = of.ofp_match.from_packet(packet, event.port)
			msg.idle_timeout = 10
			msg.hard_timeout = 30
			msg.actions.append(of.ofp_action_output(port = port))
			msg.data = event.ofp # 6a
			self.connection.send(msg)

class l2_learning (object):
	"""
		This is the Controller Class, which gets the events from the switches.
  		Waits for OpenFlow switches to connect and makes them learning switches.
  	"""

	def __init__ (self, transparent):
  		core.openflow.addListeners(self)
		self.transparent = transparent
		self.hosts = {}
		# Spawn a thread to monitor the ARP request state
		# ARPSpoofDetection.startARPStateMonitor()

	def _handle_core_ComponentRegistered (self, event):
		if event.name == "host_tracker":
			event.component.addListenerByName("HostEvent",self.__handle_host_tracker_HostEvent)
  	
	def __handle_host_tracker_HostEvent (self, event):
		h = str(event.entry.macaddr)
		s = dpid_to_str(event.entry.dpid)
		if event.leave:
			# Host leaving, delete the entry
			if h in self.hosts:
				del self.hosts[h]
		else:
			# Add (host,switch) to the hosts hash table
			self.hosts[h] = s
			print "Host "+h+" Added to "+s

	def _handle_ConnectionUp (self, event):
		print "SWITCH CONNECTED\n\n"
		log.debug("Connection %s" % (event.connection,))
		sw = LearningSwitch(event.connection, self.transparent)

	def _handle_HostEvent (self, event):
		print "Host connected\n"
		print event.entry
		print "\n"

def launch (transparent=False, hold_down=_flood_delay):
  	"""
  	Starts an L2 learning switch.
  	"""
  	try:
		global _flood_delay
		_flood_delay = int(str(hold_down), 10)
		assert _flood_delay >= 0
	except:
		raise RuntimeError("Expected hold-down to be a number")
	core.registerNew(l2_learning, str_to_bool(transparent))
