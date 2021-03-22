#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
script to communicate with a ZVT payment Terminal
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


# Im testbetrieb egal
# geht unverschlüsselt durchs LAN
PASSWORD='111111'

# trigger a payment by putting a json file to this location:
PATH='/tmp/centbetrag.json'

g_beleg = ''

# example:
#{
#        "centbetrag":2342 
#}




# manchmal nutzlos
# hängt wohl von der config ab
# Das funktioniert bei printLine 06 D1
# aber nicht bei PrintBlock
def printer(lines_of_text):
    belege =''
    #print('--------printer-----------')
    for line in lines_of_text:
    #    print(line)
        belege = belege + line + '\n'
    #print('--------printer-EOF-------')
    return belege
    
    
def write_json(belege,ergebnis):
    #print ('-----write_json----')
    #print (belege)
    #print (ergebnis)
    mydict = { 
              "belege"  : belege, 
              "ergebnis": ergebnis
              }
    with open('out.json', 'w') as json_file:
        json.dump(mydict, json_file)
    
   
   
   
def zahlvorgang():
    with open(PATH) as f:
        y = json.load(f)
    #print ("Betrag:" , y["centbetrag"])
    #print (type(y["centbetrag"]))
    centbetrag= y["centbetrag"]
    #print ("Betrag:" , centbetrag)
    if (centbetrag > 0 ):
        if e.payment(amount_cent=centbetrag):
            #print('------------last_printout:------------------')
            # da kam erst nix, nach dem ich den simulator verwendet habe, dann schon.
            # hat mit TLV container zu tun ?
            belege = printer(e.last_printout())
            e.wait_for_status()
            ergebnis = 'SUCCESS'
        else:
            belege = printer(e.last_printout()) 
            e.wait_for_status()
            ergebnis = 'FAILED'
    write_json(belege,ergebnis)
    os.remove(PATH)




if __name__ == '__main__':
    #zahlvorgang()

    e = ECR(device=URL , password=PASSWORD )
    # reenable logging:
    #e.transport.slog = ecr_log

    e.register(config_byte=Registration.generate_config(
            ecr_prints_receipt=True,        # MH
            ecr_prints_admin_receipt=True,
            ecr_controls_admin=False,
            ecr_controls_payment=False,
            ecr_use_print_lines=True  ))
    
    while (True):
        if os.path.isfile(PATH):
            #print (PATH , " gefunden")
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

            
