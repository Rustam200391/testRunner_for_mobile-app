function OnUpdate(doc, meta) {
    var expiry = Math.round((new Date()).getTime() / 1000) + 30;
    docTimer(timerCallback, meta.id, expiry);
}
function OnDelete(meta) {
    var expiry = Math.round((new Date()).getTime() / 1000) + 30;
    cronTimer(NDtimerCallback, meta.id, expiry);
}
function NDtimerCallback(docid, expiry) {
    delete dst_bucket[docid];
}
function timerCallback(docid, expiry) {
    dst_bucket[docid] = 'from timerCallback';
}