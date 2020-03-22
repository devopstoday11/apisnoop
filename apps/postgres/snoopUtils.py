import os
import json
from urllib.request import urlopen, urlretrieve
from string import Template
import requests
import re
from copy import deepcopy
from functools import reduce
from collections import defaultdict
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import subprocess
import warnings
from tempfile import mkdtemp
import time
import glob

GCS_LOGS="https://storage.googleapis.com/kubernetes-jenkins/logs/"
DEFAULT_BUCKET="ci-kubernetes-gci-gce"
K8S_GITHUB_RAW= "https://raw.githubusercontent.com/kubernetes/kubernetes/"
# Why do we have to had this?
# The k8s VERB (aka action) mapping to http METHOD
# Our audit logs do NOT contain any mention of METHOD, only the VERB
VERB_TO_METHOD={
    'get': 'get',
    'list': 'get',
    'proxy': 'proxy',
    'create': 'post',
    'post':'post',
    'put':'post',
    'update':'put',
    'patch':'patch',
    'connect':'connect',
    'delete':'delete',
    'deletecollection':'delete',
    'watch':'get'
}
IGNORED_ENDPOINTS=[
    'metrics',
    'readyz',
    'livez',
    'healthz',
    'finalize', # recently came up, am unsure what this or finalize-api mean or if we should be tracking it
    'finalize-api',
    'status' # hunch is this was a removed endpoint...but does not show in swagger.json
]
# TODO: answer question: what are finalizers and the finalize-api?
DUMMY_URL_PATHS =[
    'example.com',
    'kope.io',
    'snapshot.storage.k8s.io',
    'discovery.k8s.io',
    'metrics.k8s.io',
    'wardle.k8s.io'
]

def get_json(url):
    """Given a json url path, return json as dict"""
    body = urlopen(url).read()
    data = json.loads(body)
    return data

def determine_bucket_job(custom_bucket=None, custom_job=None):
    """return tuple of bucket, job, using latest succesfful job of default bucket if no custom bucket or job is given"""
    #establish bucket we'll draw test results from.
    baseline_bucket = os.environ['APISNOOP_BASELINE_BUCKET'] if 'APISNOOP_BASELINE_BUCKET' in os.environ.keys() else 'ci-kubernetes-e2e-gci-gce'
    bucket =  baseline_bucket if custom_bucket is None else custom_bucket
    #grab the latest successful test run for our chosen bucket.
    testgrid_history = get_json(GCS_LOGS + bucket + "/jobResultsCache.json")
    latest_success = [x for x in testgrid_history if x['result'] == 'SUCCESS'][-1]['buildnumber']
    #establish job
    baseline_job = os.environ['APISNOOP_BASELINE_JOB'] if 'APISNOOP_BASELINE_JOB' in os.environ.keys() else latest_success
    job = baseline_job if custom_job is None else custom_job
    return (bucket, job)

def fetch_swagger(bucket, job):
    """fetches swagger for given bucket and job and returns it, and its appropariate metadata, in a dict"""
    metadata_url = ''.join([GCS_LOGS, bucket, '/', job, '/finished.json'])
    metadata = json.loads(urlopen(metadata_url).read().decode('utf-8'))
    commit_hash = metadata["version"].split("+")[1]
    swagger_url =  ''.join([K8S_GITHUB_RAW, commit_hash, '/api/openapi-spec/swagger.json'])
    swagger = json.loads(urlopen(swagger_url).read().decode('utf-8')) # may change this to ascii
    return (swagger, metadata, commit_hash);

def merge_into(d1, d2):
    for key in d2:
        if key not in d1 or not isinstance(d1[key], dict):
            d1[key] = deepcopy(d2[key])
        else:
            d1[key] = merge_into(d1[key], d2[key])
    return d1

def deep_merge(*dicts, update=False):
    if update:
        return reduce(merge_into, dicts[1:], dicts[0])
    else:
        return reduce(merge_into, dicts, {})



def get_html(url):
    """return html content of given url"""
    html = urlopen(url).read()
    soup = BeautifulSoup(html, 'html.parser')
    return soup

def download_url_to_path(url, local_path, dl_dict):
    """
    downloads contents to local path, creating path if needed,
    then updates given downloads dict.
    """
    local_dir = os.path.dirname(local_path)
    if not os.path.isdir(local_dir):
        os.makedirs(local_dir)
    if not os.path.isfile(local_path):
        process = subprocess.Popen(['wget', '-q', url, '-O', local_path])
        dl_dict[local_path] = process

def get_all_auditlog_links(au):
    """
    given an artifacts url, au, return a list of all
    audit.log.* within it.
    (some audit.logs end in .gz)
    """
    soup = get_html(au)
    master_link = soup.find(href=re.compile("master"))
    master_soup = get_html("https://gcsweb.k8s.io" + master_link['href'])
    return master_soup.find_all(href=re.compile("audit.log"))

def load_openapi_spec(url):
    # Usually, a Python dictionary throws a KeyError if you try to get an item with a key that is not currently in the dictionary.
    # The defaultdict in contrast will simply return an empty dict.
    cache=defaultdict(dict)
    openapi_spec = {}
    openapi_spec['hit_cache'] = {}
    swagger = requests.get(url).json()
    # swagger contains other data, but paths is our primary target
    for path in swagger['paths']:
        # parts of the url of the 'endpoint'
        path_parts = path.strip("/").split("/")
        # how many parts?
        path_len = len(path_parts)
        # current_level = path_dict  = {}
        last_part = None
        last_level = None
        path_dict = {}
        current_level = path_dict
        # look at each part of the url/path
        for part in path_parts:
            # if the current level doesn't have a key (folder) for this part, create an empty one
            if part not in current_level:
                current_level[part] = {}
                # last_part will be this part, unless there are more parts 
                last_part=part
                # last_level will be this level, unless there are more levels
                last_level = current_level
                # current_level will be this this 'folder/dict', this might be empty
                # /api will be the top level v. often, and we only set it once
                current_level = current_level[part]
        # current level is now pointing to the inmost url part hash
        # now we iterate through the http methods for this path/endpoint
        for method, swagger_method in swagger['paths'][path].items():
            # If the method is parameters, we don't look at it
            # think this method is only called to explore with the dynamic client
            if method == 'parameters':
                next
            else:
                # for the nested current_level (end of the path/url) use the method as a lookup to the operationId
                current_level[method]=swagger_method.get('operationId', '')
                # cache = {}
                # cache = {3 : {'/api','v1','endpoints'} 
                # cache = {3 : {'/api','v1','endpoints'} {2 : {'/api','v1'} 
                # cache uses the length of the path to only search against other paths that are the same length
                cache = deep_merge(cache, {path_len:path_dict})
                openapi_spec['cache'] = cache
    return openapi_spec

def format_uri_parts_for_proxy(uri_parts):
    formatted_parts=uri_parts[0:uri_parts.index('proxy')]
    formatted_parts.append('proxy')
    formatted_parts.append('/'.join(
        uri_parts[uri_parts.index('proxy')+1:]))
    return formatted_parts

def find_operation_id(openapi_spec, event):
  method=VERB_TO_METHOD[event['verb']]
  url = urlparse(event['requestURI'])
  # 1) Cached seen before results
  # Is the URL in the hit_cache?
  if url.path in openapi_spec['hit_cache']:
    # Is the method for this url cached?
    if method in openapi_spec['hit_cache'][url.path].keys():
      # Useful when url + method is already hit multiple times in an audit log
      return openapi_spec['hit_cache'][url.path][method]
    # part of the url of the http/api request
  uri_parts = url.path.strip('/').split('/')
  # IF we git a proxy component, the rest of this is just parameters and we don't "count" them
  if 'proxy' in uri_parts:
    uri_parts = format_uri_parts_for_proxy(uri_parts)
    # We index our cache primarily on part_count
  part_count = len(uri_parts)
  # INSTEAD of try: except: maybe look into if cache has part count and complain explicitely with a good error
  try: # may have more parts... so no match
    # If we hit a length / part_count that isn't in the APISpec... this an invalid api request
    # our load_openapispec should populate all possible url length in our cache
      cache = openapi_spec['cache'][part_count]
  except Exception as e:
    # If you hit here, you are debugging... hence the warnings
    warnings.warn("part_count was:" + part_count)
    warnings.warn("spec['cache'] keys was:" + openapi_spec['cache'])
    raise e
  last_part = None
  last_level = None
  current_level = cache
  for idx in range(part_count):
    part = uri_parts[idx]
    last_level = current_level
    if part in current_level:
      current_level = current_level[part] # part in current_level
    elif idx == part_count-1:
      if part in IGNORED_ENDPOINTS or 'discovery.k8s.io' in uri_parts:
        return None
      variable_levels=[x for x in current_level.keys() if '{' in x] # vars at current(final) level?
      # If at some point in the future we have more than one... this will let un know
      if len(variable_levels) > 1:
        raise "If we have more than one variable levels... this should never happen."
      # inspect that variable_levels is not zero in length.  This indicates some new, spec-less uri
      if not variable_levels:
        print("NOTICE: uri part found that is not in apis spec.")
        print("URI: " + "/".join(uri_parts))
        return none
      variable_level=variable_levels[0] # the var is the next level
      # TODO inspect that variable level is a key for current_level
      current_level = current_level[variable_level] # variable part is final part
    else:
      next_part = uri_parts[idx+1]
      # TODO reduce this down to , find the single next level with a "{" in it 
      variable_levels=[x for x in current_level.keys() if '{' in x]
      if not variable_levels: # there is no match
        if part in DUMMY_URL_PATHS or uri_parts == ['openapi', 'v2']: #not part of our spec
          return None
        else:
          # TODO this is NOT valid, AND we didn't plan for it
          print(url.path)
          return None
      next_level=variable_levels[0]
      # except Exception as e: # TODO better to not use try/except (WE DON"T HAVE ANY CURRENT DATA")
      current_level = current_level[next_level] #coo
  try:
    op_id=current_level[method]
  except Exception as err:
    warnings.warn("method was:" + method)
    warnings.warn("current_level keys:" + current_level.keys())
    raise err
  if url.path not in openapi_spec['hit_cache']:
    openapi_spec['hit_cache'][url.path]={method:op_id}
  else:
    openapi_spec['hit_cache'][url.path][method]=op_id
  return op_id

def download_and_process_auditlogs(bucket,job):
    """
    Grabs all audits logs available for a given bucket/job, combines them into a
    single audit log, then returns the path for where the raw combined audit logs are stored.
    The processed logs are in json, and include the operationId when found.
    """
    # BUCKETS_PATH = 'https://storage.googleapis.com/kubernetes-jenkins/logs/'
    ARTIFACTS_PATH ='https://gcsweb.k8s.io/gcs/kubernetes-jenkins/logs/'
    K8S_GITHUB_REPO = 'https://raw.githubusercontent.com/kubernetes/kubernetes/'
    downloads = {}
    # bucket_url = BUCKETS_PATH + bucket + '/' + job + '/'
    artifacts_url = ARTIFACTS_PATH + bucket + '/' +  job + '/' + 'artifacts'
    download_path = mkdtemp( dir='/tmp', prefix='apisnoop-' + bucket + '-' + job ) + '/'
    combined_log_file = download_path + 'audit.log'
    swagger, metadata, commit_hash = fetch_swagger(bucket, job)

    # download all metadata
    # job_metadata_files = [
    #     'finished.json',
    #     'artifacts/metadata.json',
    #     'artifacts/junit_01.xml',
    #     'build-log.txt'
    # ]
    # for jobfile in job_metadata_files:
    #     download_url_to_path( bucket_url + jobfile,
    #                           download_path + jobfile, downloads )

    # download all logs
    log_links = get_all_auditlog_links(artifacts_url)
    for link in log_links:
        log_url = link['href']
        log_file = download_path + os.path.basename(log_url)
        download_url_to_path( log_url, log_file, downloads)

    # Our Downloader uses subprocess of curl for speed
    for download in downloads.keys():
        # Sleep for 5 seconds and check for next download
        while downloads[download].poll() is None:
            time.sleep(5)

    # Loop through the files, (z)cat them into a combined audit.log
    with open(combined_log_file, 'ab') as log:
        for logfile in sorted(
                glob.glob(download_path + '*kube-apiserver-audit*'), reverse=True):
            if logfile.endswith('z'):
                subprocess.run(['zcat', logfile], stdout=log, check=True)
            else:
                subprocess.run(['cat', logfile], stdout=log, check=True)

    # Process the resulting combined raw audit.log by adding operationId
    swagger_url = K8S_GITHUB_REPO + commit_hash + '/api/openapi-spec/swagger.json'
    openapi_spec = load_openapi_spec(swagger_url)
    infilepath=combined_log_file
    outfilepath=combined_log_file+'+opid'
    with open(infilepath) as infile:
        with open(outfilepath,'w') as output:
            for line in infile.readlines():
                event = json.loads(line)
                event['operationId']=find_operation_id(openapi_spec,event)
                output.write(json.dumps(event)+'\n')
    return outfilepath

def json_to_sql(bucket,job,auditlog_path):
    """
      Turns json+audits into load.sql
    """
    try:
        sql = Template("""
CREATE TEMPORARY TABLE raw_audit_event_import (data jsonb not null) ;
COPY raw_audit_event_import (data)
FROM '${audit_logfile}' (DELIMITER e'\x02', FORMAT 'csv', QUOTE e'\x01');

INSERT INTO raw_audit_event(bucket, job,
                             audit_id, stage,
                             event_verb, request_uri,
                             operation_id,
                             data)
SELECT '${bucket}', '${job}',
       (raw.data ->> 'auditID'), (raw.data ->> 'stage'),
       (raw.data ->> 'verb'), (raw.data ->> 'requestURI'),
       (raw.data ->> 'operationId'),
       raw.data
  FROM raw_audit_event_import raw;
        """).substitute(
            audit_logfile = auditlog_path,
            bucket = bucket,
            job = job
        )
        return sql
    except:
        return "something unknown went wrong"
