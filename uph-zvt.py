#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
script to execute a payment process.
"""
from ecrterm.ecr import ECR, ecr_log
from ecrterm.packets.base_packets import Registration
import sys
import os
import time
import json

# IP des Terminals
# default ZVT Port: 20007
URL='socket://192.168.8.194:20007'
#URL='socket://IP_ADRESSE:20007'

# Im testbetrieb egal
# geht unverschlüsselt durchs LAN
PASSWORD='111111'
PATH='/tmp/centbetrag.json'


# doch nicht nutzlos
# hängt wohl von der config ab
def printer(lines_of_text):
    print('--------printer-----------')
    for line in lines_of_text:
        print(line)
    print('--------printer-EOF-------')
    
def zahlvorgang():
    
    with open(PATH) as f:
        y = json.load(f)

    #print ("Betrag:" , y["centbetrag"])
    #print (type(y["centbetrag"]))
    centbetrag= y["centbetrag"]
    print ("Betrag:" , centbetrag)
    if (centbetrag > 0 ):
    
    
        if e.payment(amount_cent=centbetrag):
            #print('------------last_printout:------------------')
            # da kam erst nix, nach dem ich den simulator verwendet habe, dann schon.
            printer(e.last_printout())
            e.wait_for_status()
            #e.show_text(
            #    lines=[' :-) ', ' ', 'Zahlung erfolgt'], beeps=1)
            print('SUCCESS')
        else:
            e.wait_for_status()
            #e.show_text(
            #    lines=[' :-( ', ' ', 'Vorgang abgebrochen'],
            #    beeps=2)
            print('FAILED')
            
    os.remove(PATH)




if __name__ == '__main__':
    #zahlvorgang()

    e = ECR(device=URL , password=PASSWORD )
    # reenable logging:
    #e.transport.slog = ecr_log

    e.register(config_byte=Registration.generate_config(
            ecr_prints_receipt=True,        # MH
            ecr_prints_admin_receipt=True,
            ecr_controls_admin=True,
            ecr_controls_payment=True))
    
    while (True):
        if os.path.isfile(PATH):
            print (PATH , " gefunden")
            zahlvorgang()
        else:
            time.sleep(3)
            e.wait_for_status()
            status = e.status()
                # normalerweise ist status = 0
            print (time.ctime(), " Status:", status)
            if status:
                    print('Status code of PT is %s' % status)
                    # laut doku sollte 0x9c bedeuten, ein tagesabschluss erfolgt
                    # bis jetzt unklar ob er es von selbst ausführt.

                    if status == 0x9c:
                        print('End Of Day')
                        e.end_of_day()
                        # last_printout() would work too:
                        printer(e.daylog)
                    else:
                        print('Unknown Status Code: %s' % status)
                        # status == 0xDC for ReadCard (06 C0) -> Karte drin.
                        # 0x9c karte draussen.

            
