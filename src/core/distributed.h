#if defined(_MSC_VER)
#define NOMINMAX
#pragma once
#endif

#ifndef PBRT_CORE_DISTRIBUTED_H
#define PBRT_CORE_DISTRIBUTED_H

// core/distributed.h*
#include "pbrt.h"
#include "geometry.h"
#include <string>
#include <iostream>
// #include <sstream>
#include <zmq.hpp>
#include <queue>
#include <set>


namespace pbrt {

std::string ServerAddress();

std::string ClientAddress();


// https://github.com/booksbyus/zguide/blob/master/examples/C%2B%2B/zhelpers.hpp

bool RecvNoEINTR(zmq::socket_t &socket, zmq::message_t *message_ptr, int flags = 0);

bool SendNoEINTR(zmq::socket_t &socket, zmq::message_t &message, int flags = 0);

std::string s_recv (zmq::socket_t &socket);

bool s_send (zmq::socket_t &socket, const std::string &string);

//  Sends string as 0MQ string, as multipart non-terminal
bool s_sendmore (zmq::socket_t &socket, const std::string &string);

std::string s_set_id (zmq::socket_t &socket, const int id);

enum DistributedMessageType { ready, result, job, terminate, ack };

DistributedMessageType t_recv (zmq::socket_t &socket);

bool t_send (zmq::socket_t &socket, const DistributedMessageType type);

bool t_send_more (zmq::socket_t &socket, const DistributedMessageType type);

int i_recv (zmq::socket_t &socket);

bool i_send (zmq::socket_t &socket, const int number);

bool i_send_more (zmq::socket_t &socket, const int number);

// End zmq helper

typedef std::function<void(const int, void *, const size_t)> JobHandler;

class DistributedServer {
public:
    DistributedServer(const std::string& address, const std::string& job_context,
                      const int num_jobs, const int num_workers, JobHandler handler) : 
    address(address), jobContext(job_context), context(1), socket(context, ZMQ_REP),
    nWorkers(num_workers), handler(handler) {
        for (int i = 0; i < num_jobs; i++) jobs.push(i);
    }
    DistributedServer(const int num_jobs, JobHandler handler) : 
    DistributedServer(ServerAddress(), PbrtOptions.distContext, num_jobs, 
                      PbrtOptions.nWorkers, handler) {}
    void Start();
    void RecvOne();

private:
    std::string address;
    std::string jobContext; // Identifier of implicitly shared states
    zmq::context_t context; // 1 is number of io threads
    zmq::socket_t socket;
    std::queue<int> jobs;
    std::set<int> inProgress;
    JobHandler handler;
    int nWorkers; // This is only relevant for turning off workers
};

class DistributedClient {
public:
    DistributedClient(const std::string& address, const std::string& job_context) : 
    address(address), jobContext(job_context), context(1), socket(context, ZMQ_REQ) {}
    DistributedClient() : DistributedClient(ClientAddress(), PbrtOptions.distContext) {}
    bool NextJob(int& job_id);
    void CompleteJob(const int job_id, const void * data, size_t size);

private:
    std::string address;
    std::string jobContext; // Identifier of implicitly shared states
    zmq::context_t context; // 1 is number of io threads
    zmq::socket_t socket;
    bool connected = false;

};

}  // namespace pbrt

#endif  // PBRT_CORE_DISTRIBUTED_H
