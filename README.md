ARP-Cache-Poisoning-Attack-Mitigator-SDN
========================================
ARP Spoofing mitigation module on POX SDN controller. 

## Features
* This will prevent LAN attackers from poisoning the cache tables of the nodes.
* Minimum overhead and detection time.
* Prevent vague packets from entering the network thereby helping current SDN enabled networks to perform more efficiently.

## Setup
* ARPspoofperf.py is used for creating the test topology with the proposed solution.
* ARPspoofperfwithoutsol.py is for creating the test topology without the solution. 
* l2_learning_arp_mitigation.py is the ARP mitigation module on POX controller.

## Video describing the project.
<a href="http://www.youtube.com/watch?feature=player_embedded&v=ls-LIkGDDbc
" target="_blank"><img src="http://img.youtube.com/vi/ls-LIkGDDbc/0.jpg" 
alt="Video" width="240" height="180" border="10" /></a>

## Algorithm:
For algorithm, please refer to the paper <a href="https://www.researchgate.net/publication/299369116_Mitigating_ARP_Spoofing_Attacks_in_Software-Defined_Networks?_iepl%5BviewId%5D=Ah14uCiK19XDsPku33yZOkTs&_iepl%5BsingleItemViewId%5D=E4OuHPAwOl16ntLuC6ZpQHWc&_iepl%5BpositionInFeed%5D=26&_iepl%5BhomeFeedVariantCode%5D=nb_EU&_iepl%5BactivityId%5D=823512512204810&_iepl%5BactivityType%5D=person_add_publication&_iepl%5BactivityTimestamp%5D=1490781883&_iepl%5Bcontexts%5D%5B0%5D=homeFeed&_iepl%5BtargetEntityId%5D=PB%3A299369116&_iepl%5BinteractionType%5D=publicationTitle"> Paper </a>

### How to Run
* Run the POX controller using 
./pox.py log.level --DEBUG proto.dhcpd --network=10.1.1.0/24 --ip=10.1.1.1 forwarding.l2_learning_arp_mitigation
* Run the topology using
sudo mn --mac --controller remote --topo=single,3
