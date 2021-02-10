import datetime
import os
import pickle
import nightscout
from config import nigthscoutURL, checkDataBeforeRefresh, nightscoutDataPoints, checkFile

def checkIfNeedsToRun(lastEntry):
    myTime = datetime.datetime.now()
    if os.path.isfile(checkFile):
        myTime = pickle.load(open(checkFile, "rb"))

    if lastEntry == myTime:
        print("The Same, nothing changed, exiting...")
        exit()
    else:
        pickle.dump(lastEntry, open(checkFile, "wb"))

def getDataFromNightscout():
    api = nightscout.Api(nigthscoutURL)

    if checkDataBeforeRefresh:
        checkIfNeedsToRun(api.get_sgvs({'count': 1})[0].date)

    entries = api.get_sgvs({'count': nightscoutDataPoints})

    sgvs = []
    dates = []

    for entry in entries[::-1]:
        sgvs.append(entry.sgv)
        dates.append((entry.date + datetime.timedelta(hours=1)).strftime("%H:%M"))

    delta = entries[0].delta
    return sgvs, dates, delta