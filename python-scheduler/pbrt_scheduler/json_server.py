from pathlib import Path
import pickle
from argparse import ArgumentParser
from bottle import run, default_app, request, response, get, delete, post
from pbrt_scheduler.communication import ZmqClient
from pbrt_scheduler.core import MessageType, Message


def get_backend():
    app = default_app()
    address = app.config['backend_address']
    return ZmqClient(address=address, serializer=pickle.dumps, deserializer=pickle.loads)

def handle_backend_query_msg(resp):
    if resp.type == MessageType.error:
        response.status = 400
    else:
        response.status = 200
    return resp.data

@get('/jobs')
def jobs():
    di = request.json
    msg = Message(MessageType.api_query_jobs, {})
    backend_client = get_backend()
    resp = backend_client.request(msg)
    return handle_backend_query_msg(resp)

@get('/workers')
def workers():
    di = request.json
    msg = Message(MessageType.api_query_workers, {})
    backend_client = get_backend()
    resp = backend_client.request(msg)
    return handle_backend_query_msg(resp)

@post('/jobs/<job_name>')
def create_job(job_name):
    di = request.json
    di['context_name'] = job_name
    msg = Message(MessageType.api_query_workers, di)
    backend_client = get_backend()
    resp = backend_client.request(msg)
    return handle_backend_query_msg(resp)

@get('/jobs/<job_name>')
def get_job(job_name):
    di = {'job_name': job_name}
    msg = Message(MessageType.api_query_job, di)
    backend_client = get_backend()
    resp = backend_client.request(msg)
    return handle_backend_query_msg(resp)

@delete('/jobs/<job_name>')
def delete_job(job_name):
    di = {'job_name': job_name}
    msg = Message(MessageType.api_query_job, di)
    backend_client = get_backend()
    resp = backend_client.request(msg)
    return handle_backend_query_msg(resp)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--backend-port', default=13480, type=int,
                        help='port for communicating with backend')
    parser.add_argument('--frontend-port', default=8080, type=int,
                        help='port for accepting requests')
    parser.add_argument('--storage-folder', default=8080, type=int,
                        help='folder for storing updates')
    args = parser.parse_args()

    app = default_app()
    app.config['backend_address'] = 'tcp://127.0.0.1:{}'.format(args.backend_port)
    app.config['file_folder'] = args.storage_folder

    run(host='localhost', port=8080, debug=True, reloader=True)
