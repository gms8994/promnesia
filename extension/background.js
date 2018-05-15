// import Visit from 'common.js'; does not work???

// measure slowdown? Although it's async, so it's fine probably
var all_urls;

function refreshMap (cb /* Map[Url, Visits] -> Void */) {
    console.log("Urls map refresh requested!");
    chrome.storage.local.get(['history_json'], function(result) {
        var histfile = result.history_json;
        var xhr = new XMLHttpRequest();
        xhr.onreadystatechange = function() {
            // ugh, ideally should check that status is 200 etc, but that doesn't seem to work =/
            // TODO maybe swallowing exceptions here is a good idea?
            // could be paranoid and ignore if all_urls is already set?
            if (xhr.readyState != XMLHttpRequest.DONE) {
                return;
            }
            var map = JSON.parse(xhr.responseText);
            var len = Object.keys(map).length;
            console.log("Loaded map of length ", len);
            if (len > 0) {
                all_urls = {};
                Object.keys(map).map(function (key, index) {
                    var xxx = map[key];
                    all_urls[key] = new Visits(xxx[0], xxx[1]);
                });
                if (cb) {
                    cb(all_urls);
                }
                // TODO remove listener?
            }
        };
        xhr.open("GET", 'file:///' + histfile, true);
        xhr.send();
        // ugh, fetch api doesn't work with local uris
    });
}

function getMap(cb /* Map[Url, Visits] -> Void */) {
    // not sure why is this even necessary... just as extensions is running, all_urls is getting set to null occasionally
    if (all_urls) {
        cb(all_urls);
    } else {
        refreshMap(cb);
    }
}


chrome.runtime.onInstalled.addListener(function () {refreshMap(null); });

var TIME_FORMAT = "%d %b %Y %H:%M"; // TODO make sure it's consistent with python..

function getVisits(url, cb /* Visits -> Void */) {
}

chrome.tabs.onUpdated.addListener(function(tabId, changeInfo, tab) {
    // TODO ugh no simpler way??
    chrome.tabs.query({'active': true}, function (tabs) {
        // TODO why am I getting multiple results???
        var url = tabs[0].url;
        getVisits(url, function (visits) {
            if (visits) {
                chrome.browserAction.setIcon({
                    path: "ic_visited_48.png",
                    tabId: tab.id
                });
                chrome.browserAction.setTitle({
                    title: "Was visited! " + String(visits),
                    tabId: tab.id
                });
            } else {
                chrome.browserAction.setIcon({
                    path: "ic_not_visited_48.png",
                    tabId: tab.id
                });
                chrome.browserAction.setTitle({
                    title: "Was not visited",
                    tabId: tab.id
                });
            }
        });
    });
});

chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
    if (request.method == 'getVisits') {
        chrome.tabs.query({'active': true}, function (tabs) {
            var url = tabs[0].url;
            getVisits(url, function (visits) {
                sendResponse(visits);
            });
        });
        return true; // this is important!! otherwise message will not be sent?
    } else if (request.method == 'refreshMap') {
        refreshMap();
        return true;
    }
    return false;
});
