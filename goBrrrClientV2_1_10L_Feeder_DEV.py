##########################################################
# goBrrrClient V2.1.10
#                - goBrrrClient - 
#
# Descritption: Recieves market indicator driven
#   panic sell recommendations from goBrrrClient web service.
#   Intended use is to augment your PT Bot's
#   current strat to kill bags when in
#   a strong bear market state
#
#   Last updated: [18MAR2021 - 00:14:00]
#   Author: slid3r
#
##########################################################

from datetime import datetime
import re
import os
import time
import sys
import requests
import configparser
import select
import json
import termios
import logging
import socket


myVersion = "2.1.10"
myHostname = socket.gethostname()
logging.basicConfig(filename='goBrrr.log', filemode='a', format='%(asctime)s - %(message)s', datefmt='%m-%d-%Y %H:%M:%S %z', level=logging.INFO)

PTBotPort = PTBotIP = PTBotAPIToken = your_goBrrr_key = Panic_Sell = Appsettings_JSON_Path = Allow_Direct_API = Exchange_API_Key = Exchange_API_SECRET = Write_To_Log = Overwrite_Previous_Log = Set_SOM = Panic_Sell_SOM_Only = Panic_Sell_DCA = MARGIN_TRADING = TEST_MODE = EXCHANGE = INITIAL_SOM = 0
coinIDs = {}
timeRelease = {}

def loadConfig():
    global PTBotPort, PTBotIP, PTBotAPIToken, your_goBrrr_key, Panic_Sell, Appsettings_JSON_Path, Allow_Direct_API, Exchange_API_Key, Exchange_API_SECRET, Write_To_Log, Overwrite_Previous_Log, Panic_Sell_DCA, Panic_Sell_SOM_Only, Set_SOM
    config = configparser.ConfigParser()
    config.read('config.ini')

    # Read in config.ini
    try:
        PTBotPort = config.get('PT Bot Settings','PTBot_Port')
        PTBotIP = config.get('PT Bot Settings','PTBot_IP_ADDRESS')
        PTBotAPIToken = config.get('PT Bot Settings','PTBot_API_Token')
        Appsettings_JSON_Path = config.get('PT Bot Settings','Appsettings_JSON_Path')
        your_goBrrr_key = config.get('Your goBrrr Key','goBrrr_Key')
        Set_SOM = config.get('Set SOM', 'Set_SOM')
        Panic_Sell = config.get('Panic Sell','Panic_Sell')
        Panic_Sell_SOM_Only = config.get('Panic Sell','Panic_Sell_SOM_Only')
        Panic_Sell_DCA = config.get('Panic Sell','Panic_Sell_DCA')
        Allow_Direct_API = config.get('Direct API', 'Allow_Direct_API')
        Exchange_API_Key = config.get('Direct API', 'Exchange_API_Key')
        Exchange_API_SECRET = config.get('Direct API', 'Exchange_API_SECRET')
        Write_To_Log = config.get('Log File', 'Write_To_Log')
        Overwrite_Previous_Log = config.get('Log File', 'Overwrite_Previous_Log')
    except:
        print("Your config.ini file is not formatted properly, please see https://github.com/goBrrrSolutions/Clients/blob/main/goBrrrClient/v2/config.ini ")

def getSettings():
    PTURL = "http://" + PTBotIP + ":" + PTBotPort + "/api/v2/account/settings"
    r = requests.get(PTURL, params={'token': PTBotAPIToken}, headers = {"Content-Type": "application/json"})
    myJson = r.json()
    global MARGIN_TRADING
    global TEST_MODE
    global EXCHANGE
    global Panic_Sell
    for key, val in myJson.items():
        if (key == "TEST_MODE"):
            TEST_MODE = val
            print("** Profit Trailer running in paper mode: " + str(TEST_MODE))
        if (key == "MARGIN_TRADING"):
            MARGIN_TRADING = val
            print("** Profit Trailer trading on margin: " + str(MARGIN_TRADING))
        if (key == "EXCHANGE"):
            EXCHANGE = val
            print("** Profit Trailer trading on exchange: " + str(EXCHANGE))
    print("** Panic_Sell configured as: " + str(Panic_Sell))

# Generate a universal timestamp
def getTimestamp():
    nowTime = datetime.now()
    retTime = nowTime.strftime(" - [%Y/%m/%d %H:%M:%S]")
    return retTime

class noLogger(object):
    def __init__(self):
        self.terminal = sys.stdout

    def write(self, message):
        self.terminal.write(message)
        self.terminal.flush()

    def flush(self):
        pass   

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open("psomt.log", "a")

    def write(self, message):
        self.terminal.write(message)
        self.terminal.flush()
        self.log.write(message)
        self.log.flush()

    def flush(self):
        pass

# Check goBrrrClient webservice for current state
def checkLatestVersion():
    currentAppSettingsVersion = updateAppSettings()
    print("Current appsettings version: " + currentAppSettingsVersion)
    try:
        thisPayload = {'key':your_goBrrr_key, 'version':currentAppSettingsVersion}
        r = requests.post('https://gobrrrsolutions.com/cgi-bin/update.php', data = thisPayload)
        if (r.text.rstrip() != "false"):
            myAppSettings = open(Appsettings_JSON_Path, "w")
            for line in r.text.split('\n'):
                myAppSettings.write(line)
            myAppSettings.close()
            currentAppSettingsVersion = updateAppSettings()
            print("Upgraded appsettings.json to latest version: " + currentAppSettingsVersion)
        else:
            print("Current appsettings.json is already latest version")
            print(" - goBrrr appsettings.json version: " + currentAppSettingsVersion)
    except Exception as e: 
        print(e)
    # except:
        # print(" ## Network or DNS error encountered, please stand by 60 seconds or press 'c' key to continue ...")
        

def updateAppSettings():
    with open(Appsettings_JSON_Path) as f:
        first_line = f.readline()
        # print(first_line.strip())
    f.close()
    pattern = '\d+\.\d+\.\d+'
    if (re.findall(pattern, first_line)):
        myVersionNumber = re.findall(pattern, first_line)
        return myVersionNumber[0]
    else:
        return '1'
    
def loadState():
    global coinIDs
    try:
        r = requests.post('https://gobrrrsolutions.com/cgi-bin/coinlist.php', data = {'key':your_goBrrr_key})
        myCoinJson = json.loads(r.text)
        for (coinName, uniqueId) in myCoinJson.items():
            if (coinName == "ONEINCHUSDT"):
                coinName = "1INCHUSDT"
            currentUID = uniqueId["uid"]
            coinIDs[coinName] = currentUID
    except:
        print("** Error loading initial coin list UIDs - aborting")
        exit(0)
        
def checkState():
    checkIDs = {}
    try:
        r = requests.post('https://gobrrrsolutions.com/cgi-bin/coinlist.php', data = {'key':your_goBrrr_key})
        myCoinJson = json.loads(r.text)
        for (coinName, uniqueId) in myCoinJson.items():
            if (coinName == "ONEINCHUSDT"):
                coinName = "1INCHUSDT"
            currentUID = uniqueId["uid"]
            checkIDs[coinName] = currentUID
        compareIds(checkIDs)
    except Exception as e: 
        print(e)
        
def getPairsJson():
    try:
        PTURL = "http://" + PTBotIP + ":" + PTBotPort + "/api/v2/data/pairs"
        r = requests.get(PTURL, params={'token': PTBotAPIToken}, headers = {"Content-Type": "application/json"})
        myJson = r.json()
        return myJson
    except Exception as e: 
        print(e)

def getDcaJson():
    try:
        PTURL = "http://" + PTBotIP + ":" + PTBotPort + "/api/v2/data/dca"
        r = requests.get(PTURL, params={'token': PTBotAPIToken}, headers = {"Content-Type": "application/json"})
        myJson = r.json()
        return myJson
    except Exception as e: 
        print(e)

def getPendingJson():
    try:
        PTURL = "http://" + PTBotIP + ":" + PTBotPort + "/api/v2/data/pending"
        r = requests.get(PTURL, params={'token': PTBotAPIToken}, headers = {"Content-Type": "application/json"})
        myJson = r.json()
        return myJson
    except Exception as e: 
        print(e)

def setBuilder(inJson, inString):
    global EXCHANGE
    retDict = {}
    pairsString = inString + ":"
    for thisLine in inJson:
        for key,val in thisLine.items():
            if key == "market": 
                thisPair = val
                if EXCHANGE == "KUCOIN":
                    thisPair = re.sub('-USDT$', 'USDT', thisPair)
            if key == "totalAmount":
                thisAmount = val
            if key == "currentValue":
                thisPairValue = val
            if key == "currency":
                thisCurrency = val
            if key == "base":
                thisBase = val
            if key == "currentPrice":
                thisPtCurrentPrice = val
            if key == "avgPrice":
                thisPtAvgPrice = val
            if key == "percChange":
                thisPtPercentChange = val
            if key == "profit":
                thisProfit = val
        pairsString = pairsString + " " + thisPair
        retDict[thisPair] = {'currency': thisCurrency, 'base': thisBase, 'quantity': thisAmount, 'ptCurrentValue': thisPairValue, 'ptCurrentPrice': thisPtCurrentPrice, 'ptAvgPrice': thisPtAvgPrice, 'ptPercentChange': thisPtPercentChange, 'ptProfit': thisProfit}
    # print(pairsString)
    #  logging.info(str(pairsString))
    return retDict
    
def listBags():
    pendingSet = pairSet = dcaSet = {}
    pendingJson = getPendingJson()
    pairsJson = getPairsJson()
    dcaJson = getDcaJson()
    if (len(pendingJson) != 0):
        pendingStr = "{Pending: " + pendingJson[0]["market"]
        for i in range(1, len(pendingJson)):
            pendingStr += ", " + pendingJson[i]["market"]
        pendingStr += "}"
        print(pendingStr)
    if (len(pairsJson) != 0):
        pairsStr = "{Pairs: " + pairsJson[0]["market"]
        for i in range(1, len(pairsJson)):
            pairsStr += ", " + pairsJson[i]["market"]
        pairsStr += "}"
        print(pairsStr)
    if (len(dcaJson) != 0):
        dcaStr = "{DCA: " + dcaJson[0]["market"]
        for i in range(1, len(dcaJson)):
            dcaStr += ", " + dcaJson[i]["market"]
        dcaStr += "}"
        print(dcaStr)

def changeSOM(setState):
    global INITIAL_SOM
    global Set_SOM
    if Set_SOM == "true":
        PTURL = "http://" + PTBotIP + ":" + PTBotPort + "/api/v2/globalSellOnlyMode"
        r = requests.post(PTURL, data = {'enabled':setState,'token':PTBotAPIToken})
        if INITIAL_SOM:
            print("Received global SOM signal, setting SOM to: " + setState)
            print("------------------------------------------------------------")
            logging.info("Received global SOM signal, setting SOM to: " + setState)
    else:
        print("Received global SOM signal, config.ini does not allow client to change state: " + setState)
        print("------------------------------------------------------------")
        logging.info("Received global SOM signal, config.ini does not allow client to change state: " + setState)

def sellSOM(inSOM):
    global Panic_Sell_SOM_Only
    if Panic_Sell_SOM_Only == "false":
        return True
    elif ( (Panic_Sell_SOM_Only == "true") and (inSOM == "true") ):
        return True
    else:
        return False

def panicTimeout():
    global timeRelease
    myCoinList = []
    rightNow = time.time()
    for coin, timeIn in timeRelease.items():
        if(rightNow - timeIn < 900):
            print("This coin currently in panic sell: " + coin, timeIn)
        else:
            print("Releasing this coin from panic sell: " + coin)
            thisSubString = subStringBuilder(coin,True)
            thisSwapString = subStringBuilder(coin,False)
            thisDCASubString = subDCAStringBuilder(coin,True)
            thisDCASwapString = subDCAStringBuilder(coin,False)
            if( (lineFinder(thisSubString,thisSwapString,"true")) or (lineFinder(thisDCASubString,thisDCASwapString,"true")) ):
                print("Releasing " + coin + " from panic sell status ...")
                logging.info("Releasing " + str(coin) + " from panic sell status ..." + str(rightNow))
                myCoinList.append(coin) # You have to make a list and pop them later because if you pop them in-line they barf
    for i in myCoinList:
        # print("Popping: " + i)
        timeRelease.pop(i)

def appsettingsResetter(inFile):
    appSettingsText = open(inFile).read()
    print("Resetting any residual panic sell true states to false ...")
    myMatch = re.findall("_panic_sell_enabled\": \"true\",",appSettingsText)
    for i in myMatch:
            appSettingsText = appSettingsText.replace("_panic_sell_enabled\": \"true\"", "_panic_sell_enabled\": \"false\"")
    with open(inFile, 'w') as f:
            f.write(appSettingsText)
            f.close()

def subStringBuilder(inCoin,inState):
    falseStringSub = "_panic_sell_enabled\": \"false\","
    trueStringSub = "_panic_sell_enabled\": \"true\","
    inCoin = re.sub('USDT$', '', inCoin)
    # print(inCoin)
    if inState:
        inCoin = "\"" + inCoin + trueStringSub
    else:
        inCoin = "\"" + inCoin + falseStringSub
    return inCoin

def subDCAStringBuilder(inCoin,inState):
    falseStringSub = "_DCA_panic_sell_enabled\": \"false\","
    trueStringSub = "_DCA_panic_sell_enabled\": \"true\","
    inCoin = re.sub('USDT$', '', inCoin)
    # print(inCoin)
    if inState:
        inCoin = "\"" + inCoin + trueStringSub
    else:
        inCoin = "\"" + inCoin + falseStringSub
    return inCoin

def lineFinder(inString,swapString,inSOM):
    global Panic_Sell, Appsettings_JSON_Path
    retValue = False
    appSettingsText = open(Appsettings_JSON_Path).read()
    myMatch = re.findall(inString,appSettingsText)
    for i in myMatch:
        if ( (Panic_Sell == "true") and (sellSOM(inSOM)) ):
            appSettingsText = appSettingsText.replace(inString,swapString)
        else:
            print("Found panic sell opportunity but no action taken as per Panic_Sell in config.ini")
    if myMatch:
        retValue = True
        if ( (Panic_Sell == "true") and (sellSOM(inSOM)) ):
            with open(Appsettings_JSON_Path, 'w') as f:
                f.write(appSettingsText)
                f.close()
        return retValue

def compareIds(inIDs):
    # client = Client(Exchange_API_Key, Exchange_API_SECRET)
    global coinIDs
    global Appsettings_JSON_Path
    global timeRelease
    global INITIAL_SOM
    global Panic_Sell, Panic_Sell_DCA, Set_SOM
    changedCoins = []
    this_SOM = str(inIDs['SOM'])
    print("Current recommended SOM state: " + this_SOM)
    print("---------------")
    if not INITIAL_SOM:
        print("First Run: Ensuring PT SOM state complies with current goBrrr web service recommended state ...")
        changeSOM(this_SOM)
        INITIAL_SOM = 1
    for (key,val) in inIDs.items():
        if key in coinIDs.keys():
            if ( (val != coinIDs[key]) and (key != 'SOM') ):
                changedCoins.append(key)
                print("Received signal for: " + str(key))
                print("------------------------------------------------------------")
                logging.info("Received signal for: " + str(key))
                coinIDs[key] = val
        else:
            changedCoins.append(key)
            print("Received signal for: " + str(key))
            print("------------------------------------------------------------")
            logging.info("Received signal for: " + str(key))
            coinIDs[key] = val
    if changedCoins:
        pendingSet = pairSet = dcaSet = {}
        pendingJson = getPendingJson()
        if pendingJson:
            pendingSet = setBuilder(pendingJson, "PENDING")
            # print(pendingSet)
            time.sleep(2)
        pairsJson = getPairsJson()
        if pairsJson:
            pairSet = setBuilder(pairsJson, "PAIRS")
            # print("PAIRS SET hypens removed: ")
            # print(pairSet)
            time.sleep(2)
        dcaJson = getDcaJson()
        if dcaJson:
            dcaSet = setBuilder(dcaJson, "DCA")
            # print(dcaSet)
        for i in changedCoins:
            isCoin = 1
            if (i == "GlobalSOMDisable"):
                changeSOM("false")
                isCoin = 0
            if (i == "GlobalSOMEnable"):
                changeSOM("true")
                isCoin = 0
            if isCoin:
                if i in pairSet:
                    print("PairSet: ")
                    print(i + ": " + str(pairSet[i]['quantity']))
                    print(pairSet[i])
                    thisSubString = subStringBuilder(i,False)
                    thisSwapString = subStringBuilder(i,True)
                    if(lineFinder(thisSubString,thisSwapString,this_SOM)):
                        if ( (Panic_Sell == "true") and (sellSOM(this_SOM)) ):
                            logging.info("Selling: " + str(pairSet[i]))
                            print("We can sell this in appsettings")
                            print("Adding to timeRelease ..")
                            timeRelease[i] = time.time()
                        else:
                            logging.info("Panic_Sell requirements not met - skipped selling: " + str(pairSet[i]))
                            print("Panic_Sell requirements not met - skipped selling")
                else:
                    print(i + ": Pair not found in Pairs ...")
                if i in dcaSet:
                    print("DCASet: ")
                    print(i + ": " + str(dcaSet[i]['quantity']))
                    print(dcaSet[i])
                    thisSubString = subDCAStringBuilder(i,False)
                    thisSwapString = subDCAStringBuilder(i,True)
                    if Panic_Sell_DCA == "true":
                        if(lineFinder(thisSubString,thisSwapString,this_SOM)):
                            if ( (Panic_Sell == "true") and (sellSOM(this_SOM)) ):                            
                                logging.info("Selling: " + str(dcaSet[i]))
                                print("We can sell this in appsettings")
                                print("Adding to timeRelease ..")
                                timeRelease[i] = time.time()
                            else:
                                logging.info("Panic_Sell requirements for DCA not met - skipped selling: " + str(pairSet[i]))
                                print("Panic_Sell requirements for DCA not met - skipped selling")
                else:
                    print(i + ": Pair not found in DCA ...")

os.system('clear')        
loadConfig()

if (Write_To_Log == "true"):
    if (Overwrite_Previous_Log == "true"):
        open("goBrrr.log", 'w').close()

logging.info("First run on host: " + myHostname)
getSettings()
appsettingsResetter(Appsettings_JSON_Path)
loadState()
# checkLatestVersion()

# Let's do this!
print("*** goBrrrClientV" + myVersion + " is running. Leave this window open to protect your profits! ***")
runCount = 0

while 1:
    panicTimeout()
    print("This application will execute every 60 seconds.")
    print("Press the following HotKeys to expedite features:")
    print("'c': This will check for changes in volatile coins (default every 60 seconds)")
    print("'r': This will reload your settings from config.ini")
    print("'u': This will check to see if your current appsettings.json file is goBrrr's latest")
    print("'f': This will list your currently held bags")
    print("'q': This will exit and quit the app")
    runCount = runCount + 1
    print("Run Count: " + str(runCount))
    print("---------------")
    checkState()

    for i in range(60):
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            myInChar = sys.stdin.read(1)
            if (myInChar.lower() == "r"):
                print("Reloading config.ini")
                loadConfig()
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
            elif (myInChar.lower() == "u"):
                checkLatestVersion()
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
            elif (myInChar.lower() == "c"):
                checkState()
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
            elif (myInChar.lower() == "f"):
                listBags()
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
            elif (myInChar.lower() == "b"):
                break
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
            elif (myInChar.lower() == "q"):
                sys.exit()
                termios.tcflush(sys.stdin, termios.TCIOFLUSH)
        time.sleep(1)
    os.system('clear')
    # os.system('cls||clear')
