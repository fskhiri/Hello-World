var RestClient = require('node-rest-client').Client;
var rest = new RestClient();
var logger = require('../controllers/logController');
var config = require('./../controllers/configController');
var requestLogger = require('../controllers/logRequestController');

function has_access(token, path, method, callback){
    if (!token){
        logger.error(method.toUpperCase() + ' request ' + path + ' invalid access token (' + token + ')');
        callback({message: 'Invalid access token', code: 500}, {statusCode: 500});
        return false;
    }
    else{
        return true;
    }
}

function set_args(args, token){
    if (!args) {
        args = {};
    }

    if (!args.headers) {
        args.headers = {};
    }

    if (!args.headers['User-Agent']) {
        args.headers['User-Agent'] = config.userAgent;
    }

    if (!args.headers.Accept) {
        args.headers.Accept = 'application/json';
    }

    if (!args.headers['Content-Type']) {
        args.headers['Content-Type'] = 'application/json';
    }

    if (args.headers.authorization) {
        //Conflicts with other authorization methods used by us
        delete args.headers.authorization;
    }

    //Avoid caching issues
    args.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';

    if(args.headers.host) {
        //"Error: Hostname/IP doesn't match certificate's altnames" if host does not match
        delete args.headers.host;
    }

    if (!args.parameters) {
        args.parameters = {};
    }

    if(token){
        args.parameters.access_token = token;
    }
    return args;
}

function restCall(originalReq, method, baseUrl, path, args, callback){
    if(!method || !baseUrl || !path || !args || !callback) {
        throw 'Illegal Arguments: method:' + method + ', baseUrl:' + baseUrl + 'path' + ', args:' + args + ', callback:' + callback;
    }
    var url = baseUrl + path;
    var reqId = requestLogger.logRequestByParams(null, method, url, args.data, args.headers, args.parameters, requestLogger.Direction.Outgoing);
    rest[method](url, args, function(data, res) {
        requestLogger.logResponse(reqId, res, null, requestLogger.Direction.Incoming);
        callback(data, res);
    });
}

module.exports = {

    //GET method
    httpCall: function (method, originalReq, token, path, args, callback) {
        if(!has_access(token, path, method, callback)){
            return;
        }
        args = set_args(args, token);
        restCall(originalReq, method.toLowerCase(), config.github.apiUrl, path, args, function (data, res) {
            callback(data, res);
        });
    }
};
