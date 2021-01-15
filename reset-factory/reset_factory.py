from smartcard.CardType import AnyCardType
from smartcard.CardRequest import CardRequest
from smartcard.CardConnectionObserver import CardConnectionObserver
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.Exceptions import CardConnectionException, CardRequestTimeoutException
from smartcard.util import toHexString, toBytes
from smartcard.sw.SWExceptions import SWException

import PySimpleGUIQt as sg 

import logging 
import time

#debug
import sys
import traceback
import os 

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# a card observer that detects inserted/removed cards and initiate connection
class RemovalObserver(CardObserver):
    """A simple card observer that is notified
    when cards are inserted/removed from the system and
    prints the list of cards
    """
    def __init__(self, cc):
        self.cc=cc
        #self.observer = LogCardConnectionObserver() #ConsoleCardConnectionObserver()
            
    def update(self, observable, actions):
        (addedcards, removedcards) = actions
        for card in addedcards:
            #TODO check ATR and check if more than 1 card?
            logger.info(f"+Inserted: {toHexString(card.atr)}")
            print(f"+Inserted: {toHexString(card.atr)}")
            self.cc.card_event= "card_added"
            self.cc.card_present= True
            self.cc.cardservice= card
            self.cc.cardservice.connection = card.createConnection()
            self.cc.cardservice.connection.connect()
            #self.cc.cardservice.connection.addObserver(self.observer)
            try:
                (response, sw1, sw2) = self.cc.card_select()
                if sw1!=0x90 or sw2!=0x00:
                    self.cc.card_disconnect()
                    break
                
                # (response, sw1, sw2) = self.cc.card_reset_factory()
                # print("card_reset_factory: "+str(hex(256*sw1+sw2)))
                # if sw1!=0x90 or sw2!=0x00:
                    # self.cc.card_disconnect()
                    # print("CARD HAS BEEN RESET !")
                    # break
                
                # (response, sw1, sw2, status)= self.cc.card_get_status()
                # if (sw1!=0x90 or sw2!=0x00) and (sw1!=0x9C or sw2!=0x04):
                    # self.cc.card_disconnect()
                    # break
                # if (self.cc.needs_secure_channel):
                    # self.cc.card_initiate_secure_channel()
                
            except Exception as exc:
                logger.warning(f"Error during connection: {repr(exc)}")
         
                
        for card in removedcards:
            logger.info(f"-Removed: {toHexString(card.atr)}")
            print(f"-Removed: {toHexString(card.atr)}")
            self.cc.card_event= "card_removed"
            self.cc.card_disconnect()
            print("Please insert card again...")
            
class CardConnector:

    # define the apdus used in this script
    BYTE_AID= [0x53,0x61,0x74,0x6f,0x43,0x68,0x69,0x70] #SatoChip
    SATOCHIP_AID= [0x53,0x61,0x74,0x6f,0x43,0x68,0x69,0x70] #SatoChip
    SEEDKEEPER_AID= [0x53,0x65,0x65,0x64,0x4b,0x65,0x65,0x70,0x65,0x72]  #SatoChip
 
    def __init__(self, client=None, loglevel= logging.WARNING):
        logger.debug("In __init__")
        self.logger= logger
        self.client=client
        self.card_event= None
        self.cardtype = AnyCardType() #TODO: specify ATR to ignore connection to wrong card types?
        self.needs_2FA = None
        self.is_seeded= None
        self.setup_done= None
        self.needs_secure_channel= None
        self.sc = None
        # cache PIN
        self.pin_nbr=None
        self.pin=None
        # cardservice
        self.cardservice= None #will be instantiated when a card is inserted
        try:
            self.cardrequest = CardRequest(timeout=0, cardType=self.cardtype)
            self.cardservice = self.cardrequest.waitforcard()
            #TODO check ATR and check if more than 1 card?
            self.card_present= True
        except CardRequestTimeoutException:
            self.card_present= False
        # monitor if a card is inserted or removed
        self.cardmonitor = CardMonitor()
        self.cardobserver = RemovalObserver(self)
        self.cardmonitor.addObserver(self.cardobserver)
     
    ###########################################
    #                   Applet management                        #
    ###########################################

    def card_transmit(self, plain_apdu):
        logger.debug("In card_transmit")
        while(self.card_present):
            try:
                # #encrypt apdu
                # ins= plain_apdu[1]
                # if (self.needs_secure_channel) and (ins not in [0xA4, 0x81, 0x82, 0xFF, JCconstants.INS_GET_STATUS]):
                    # apdu = self.card_encrypt_secure_channel(plain_apdu)
                # else:
                    # apdu= plain_apdu
                    
                # transmit apdu
                (response, sw1, sw2) = self.cardservice.connection.transmit(plain_apdu)
                
                # PIN authentication is required
                if (sw1==0x9C) and (sw2==0x06):
                    (response, sw1, sw2)= self.card_verify_PIN()
                # #decrypt response
                # elif (sw1==0x90) and (sw2==0x00):
                    # if (self.needs_secure_channel) and (ins not in [0xA4, 0x81, 0x82, JCconstants.INS_GET_STATUS]):
                        # response= self.card_decrypt_secure_channel(response)
                    # return (response, sw1, sw2)
                else:
                    return (response, sw1, sw2)
                
            except Exception as exc:
                logger.warning(f"Error during connection: {repr(exc)}")
                #self.client.request('show_error',"Error during connection:"+repr(exc))
                return ([], 0x00, 0x00)
        
        # no card present
        #self.client.request('show_error','No Satochip found! Please insert card!')
        return ([], 0x00, 0x00)
        #TODO return errror or throw exception?

    def card_select(self):
        logger.debug("In card_select")
        SELECT = [0x00, 0xA4, 0x04, 0x00, 0x08]
        apdu = SELECT + CardConnector.SATOCHIP_AID
        (response, sw1, sw2) = self.card_transmit(apdu)
        
        if sw1==0x90 and sw2==0x00:
            self.card_type="Satochip"
        else:
            SELECT = [0x00, 0xA4, 0x04, 0x00, 0x0A]
            apdu = SELECT + CardConnector.SEEDKEEPER_AID
            (response, sw1, sw2) = self.card_transmit(apdu)
            if sw1==0x90 and sw2==0x00:
                self.card_type="SeedKeeper"
        
        return (response, sw1, sw2)            
    
    def card_disconnect(self):
        logger.debug('In card_disconnect()')
        self.pin= None #reset PIN
        self.pin_nbr= None
        self.is_seeded= None
        self.needs_2FA = None
        self.setup_done= None
        self.needs_secure_channel= None
        self.card_present= False
        if self.cardservice:
            self.cardservice.connection.disconnect()
            self.cardservice= None
        if self.client:
            self.client.request('update_status',False)
    
    def card_get_status(self):
        logger.debug("In card_get_status")
        cla= 0xB0
        ins= 0x3C
        p1= 0x00
        p2= 0x00
        apdu=[cla, ins, p1, p2]
        (response, sw1, sw2)= self.card_transmit(apdu)
        d={}
        if (sw1==0x90) and (sw2==0x00):
            d["protocol_major_version"]= response[0]
            d["protocol_minor_version"]= response[1]
            d["applet_major_version"]= response[2]
            d["applet_minor_version"]= response[3]
            d["protocol_version"]= (d["protocol_major_version"]<<8)+d["protocol_minor_version"] 
            if len(response) >=8:
                d["PIN0_remaining_tries"]= response[4]
                d["PUK0_remaining_tries"]= response[5]
                d["PIN1_remaining_tries"]= response[6]
                d["PUK1_remaining_tries"]= response[7]
                self.needs_2FA= d["needs2FA"]= False #default value
            if len(response) >=9:
                self.needs_2FA= d["needs2FA"]= False if response[8]==0X00 else True
            if len(response) >=10:
                self.is_seeded= d["is_seeded"]= False if response[9]==0X00 else True
            if len(response) >=11:
	                self.setup_done= d["setup_done"]= False if response[10]==0X00 else True    
            else:
                self.setup_done= d["setup_done"]= True    
            if len(response) >=12:
                self.needs_secure_channel= d["needs_secure_channel"]= False if response[11]==0X00 else True    
            else:
                self.needs_secure_channel= d["needs_secure_channel"]= False
        
        elif (sw1==0x9c) and (sw2==0x04):
            self.setup_done= d["setup_done"]= False  
            self.is_seeded= d["is_seeded"]= False
            self.needs_secure_channel= d["needs_secure_channel"]= False
            
        else:
            logger.warning(f"[card_get_status] unknown get-status() error! sw12={hex(sw1)} {hex(sw2)}")
            #raise RuntimeError('Unknown get-status() error code:'+hex(sw1)+' '+hex(sw2))
            
        return (response, sw1, sw2, d)
    
    def card_reset_factory(self):
        logger.debug("In card_reset_factory")
        apdu = [0xB0, 0xFF, 0x00, 0x00, 0x00]
        (response, sw1, sw2) = self.card_transmit(apdu)
        return (response, sw1, sw2)          
            

class HandlerSimpleGUI:
    def __init__(self, cc): 
        logger.debug("In __init__")
        sg.theme('BluePurple')
        # absolute path to python package folder of satochip_bridge ("lib")
        #self.pkg_dir = os.path.split(os.path.realpath(__file__))[0] # does not work with packaged .exe 
        if getattr( sys, 'frozen', False ):
            # running in a bundle
            self.pkg_dir= sys._MEIPASS # for pyinstaller
        else :
            # running live
            self.pkg_dir = os.path.split(os.path.realpath(__file__))[0]
        logger.debug("PKGDIR= " + str(self.pkg_dir))
        self.satochip_icon= self.icon_path("satochip.png") #"satochip.png"
        self.satochip_unpaired_icon= self.icon_path("satochip_unpaired.png") #"satochip_unpaired.png"
        self.cc=cc
    
    def icon_path(self, icon_basename):
        #return resource_path(icon_basename)
        return os.path.join(self.pkg_dir, icon_basename)
        
    def main_menu(self):
        logger.debug('In main_menu')
        
        msg_instruction=''.join([  'To perform factory reset, the card must be inserted and removed several times \n',
                                            'To proceed, follow the detailed instructions in red. \n',
                                            'WARNING: ALL DATA WILL BE WIPED FROM THE CARD! \n',
                                            'This process is irreversible!'])
        msg_copyright= ''.join([ '(c)2020 - Satochip by Toporin - https://github.com/Toporin/ \n',
                                                "This program is licensed under the GNU Lesser General Public License v3.0 \n",
                                                "This software is provided 'as-is', without any express or implied warranty.\n",
                                                "In no event will the authors be held liable for any damages arising from \n"
                                                "the use of this software."])
        
        button_color_enabled= ('#912CEE', '#B2DFEE') # purple2, lighblue2 - see https://github.com/PySimpleGUI/PySimpleGUI/blob/master/DemoPrograms/Demo_Color_Chooser_Custom.py
        button_color_disabled= ('White', 'Gray')

        btn_reset_disabled= True
        btn_reset_color= button_color_disabled
        btn_abort_disabled= True
        btn_abort_color= button_color_disabled
        action= "Please insert card to start reset process"
        counter= "Counter= ?"
        
        def update_button(card_present= True, do_update_layout=True):
            #nonlocal btn_reset_disabled, btn_reset_color, btn_abort_disabled, btn_abort_color, action 
            #logger.debug("Update_button - Card reader status: "+ str(self.cc.card_type))
            
            if (card_present):
                action= "Click on 'reset' then remove card to proceed to factory reset"
                btn_reset_disabled= False
                btn_reset_color= button_color_enabled
                btn_abort_disabled= False
                btn_abort_color= button_color_enabled
                
            else:
                action= "Please insert card to proceed to factory reset"
                btn_reset_disabled= True
                btn_reset_color= button_color_disabled
                btn_abort_disabled= True
                btn_abort_color= button_color_disabled
                
            # if self.cc.card_type=='SeedKeeper':
            # elif self.cc.card_type=='Satochip':
            # else: #no card
                
            if (do_update_layout):
                logger.debug("Update layout!")
                window['reset'].update(disabled=btn_reset_disabled)
                window['abort'].update(disabled=btn_abort_disabled)
                window['reset'].update(button_color=btn_reset_color) 
                window['abort'].update(button_color=btn_abort_color)
                window['action'].update(action)
                
        layout = [  #[sg.Text('Reset-to-Factory Tool ')],  
                        #[sg.Text('Card inserted:' + str(self.cc.card_type))],          
                        [sg.Text(msg_instruction, justification='center', relief=sg.RELIEF_SUNKEN)],
                        [sg.Text(action, key='action', justification='center', relief=sg.RELIEF_SUNKEN, text_color='red')],
                        [sg.Text(counter, key='counter', justification='center', relief=sg.RELIEF_SUNKEN, text_color='red')],
                        [sg.Button('Reset card', key='reset', disabled= btn_reset_disabled, button_color=btn_reset_color),
                            sg.Button('Abort', key='abort', disabled= btn_abort_disabled, button_color=btn_abort_color) ],
                        [sg.Text(msg_copyright, justification='center', relief=sg.RELIEF_SUNKEN)],
                        [sg.Button('Quit', key= 'quit',  disabled= False, button_color=button_color_enabled)],
                    ]      
        window = sg.Window('Reset-to-Factory Tool', layout, icon=self.satochip_icon).Finalize()   #ok
        update_button(True)
        
        while True:
            event, values = window.read(timeout=200)    
            
            if (self.cc.card_event=="card_added"):
                update_button(card_present= True, do_update_layout=True)
                self.cc.card_event= None
                continue
            elif (self.cc.card_event=="card_removed"):
                update_button(card_present= False, do_update_layout=True)
                self.cc.card_event= None
                continue
                
            if event == sg.TIMEOUT_KEY:
                continue
            elif event == 'reset':
                (response, sw1, sw2) = self.cc.card_reset_factory()
                print("card_reset_factory: "+str(hex(256*sw1+sw2)))
                if sw1==0xFF and sw2==0x00:
                    self.cc.card_disconnect()
                    print("CARD HAS BEEN RESET !")
                    action= "CARD HAS BEEN RESET TO FACTORY!"
                    window['action'].update(action)
                    counter= "Remaining counter: 0"
                    window['counter'].update(counter)
                elif sw1==0xFF and sw2==0xFF:
                    print("RESET ABORTED !")
                    action= "RESET ABORTED: you must remove card after each reset!"
                    window['action'].update(action)
                    counter= "Remaining counter: MAX"
                    window['counter'].update(counter)
                elif sw1==0xFF and sw2>0x00:
                    print("COUNTER: "+ str(sw2))
                    action= "Please remove and reinsert card to continue..."
                    window['action'].update(action)
                    counter= "Remaining counter: "+str(sw2)
                    window['counter'].update(counter)
                elif sw1==0x6F and sw2==0x00:
                    action= "The factory reset failed"
                    window['action'].update(action)
                    counter=  "Unknown error"+ str(hex(256*sw1+sw2))
                    window['counter'].update(counter)
                elif sw1==0x6D and sw2==0x00:
                    action= "The factory reset failed"
                    window['action'].update(action)
                    counter=  "Instruction not supported - error code: "+ str(hex(256*sw1+sw2))
                    window['counter'].update(counter)
                    
            elif event == 'abort':
                (response, sw1, sw2, d) = self.cc.card_get_status()
                print("RESET ABORTED: " + str(hex(256*sw1+sw2)) )
                action= "RESET ABORTED!"
                window['action'].update(action)
                counter= "Remaining counter: MAX"
                window['counter'].update(counter)
            elif event == 'quit':
                break
                
        window.close()  
        del window
        return event
            
#######

print("RESET FACTORY")
print("Please insert card in order to reset to factory...")     
cc= CardConnector()
handler= HandlerSimpleGUI(cc)

while(True):   
    
    event= handler.main_menu()   
    if event == 'quit':
        break;
    else: 
        logger.debug("Unknown event: "+ str(event))
        break;
            
            
print("END RESET FACTORY")
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            