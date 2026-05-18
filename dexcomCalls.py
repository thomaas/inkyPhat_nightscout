import datetime
import os
import pickle
from pydexcom import Dexcom, Region
from config import dexcom_username, dexcom_password, checkDataBeforeRefresh, nightscoutDataPoints, checkFile, dexcom_region

def checkIfNeedsToRun(lastEntry):
    myTime = datetime.datetime.now()
    if os.path.isfile(checkFile):
        myTime = pickle.load(open(checkFile, "rb"))

    if lastEntry == myTime:
        print("The Same, nothing changed, exiting...")
        exit(1)
    else:
        pickle.dump(lastEntry, open(checkFile, "wb"))

def getDataFromNightscout():
    dexcom = Dexcom(username=dexcom_username, password=dexcom_password, region=Region(dexcom_region))
   
    if checkDataBeforeRefresh: 
        checkIfNeedsToRun(dexcom.get_glucose_readings(max_count=1)[0].time)

    entries = dexcom.get_glucose_readings(max_count=nightscoutDataPoints)
    sgvs = []
    dates = []

    for entry in entries[::-1]:
        sgvs.append(entry.value)
        dates.append((entry.datetime + datetime.timedelta(hours=1)).strftime("%H:%M"))

    delta = 0
    if(len(entries) > 1):
        delta = entries[0].value - entries[1].value 
    return sgvs, dates, delta