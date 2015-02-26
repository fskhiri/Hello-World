var http = require('http');
var https = require('https');
var url = require('url');
var querystring = require('querystring');
var config = require('../controllers/configController');
var RestClient = require('node-rest-client').Client;
var rest = new RestClient();
var logger = require('../controllers/logController');


var jenkins = {};

jenkins.options = {
    hostname: config.jenkins.host,
    auth: config.jenkins.user + ':' + config.jenkins.token,
    port: config.jenkins.port
};

var call = function(path, method, parameter, done){
    var options = jenkins.options;
    options.method = method;

    if(parameter)
    {
        options.path = path + '?' + querystring.stringify(parameter);
    }
    else
    {
        options.path = path;
    }
    var req;
    if(config.jenkins.protocol === 'https')
    {

        req = https.request(options, function(res) {
            var data = '';
            res.on('data', function(chunk) { data += chunk; });

            res.on('end', function(){

                //get job location in queue
                var location = res.headers.location;

                var options_job = options;
                options_job.method = 'GET';
                options_job.path = url.parse(location + 'api/json').pathname;
                console.log('-----');
                console.log(options_job);
                var req_job = https.request(options_job, function(res_job) {
                    var job_data = '';
                    res_job.on('data', function(chunk) { job_data += chunk; });
                    res_job.on('end', function(){
                        console.log(job_data);
                    });
                });


                req_job.end();
                req_job.on('error', function (e) {
                    console.log(e);
                });
            });
        });

        req.end();
        req.on('error', function (e) {
            done(e, undefined);
        });
    }
    else
    {
        req = http.request(options, function(res) {
            var data = '';
            res.on('data', function(chunk) { data += chunk; });
            res.on('end', function(){
                done(undefined, res.statusCode);
            });
        });

        req.on('error', function (e) {
            done(e, undefined);
        });

        req.end();
    }
};

//wrappers for jenkins api
jenkins.buildJob = function(jobname, parameter, done){

    if(parameter)
    {
        parameter.github_api = config.github.apiUrl;
        call('/job/' + jobname + '/buildWithParameters', 'POST', parameter, done);
    }
    else
    {
        call('/job/' + jobname + '/build', 'POST', undefined, done);
    }
};

jenkins.forwardWebhook = function(path, args, callback) {

    var jenkins_url = config.jenkins.protocol + '://' + config.jenkins.host + ':' + config.jenkins.port + '/' + path;

    rest.post(jenkins_url, args, function (data, res) {
        callback(data, res);
    });
};

module.exports = jenkins;
