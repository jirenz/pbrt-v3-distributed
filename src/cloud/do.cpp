#include <iostream>
#include <string>

#include "cloud/bvh.h"
#include "cloud/integrator.h"
#include "cloud/manager.h"
#include "cloud/raystate.h"
#include "messages/serialization.h"
#include "messages/utils.h"
#include "util/exception.h"

using namespace std;
using namespace pbrt;

void usage(const char *argv0) {
    cerr << argv0 << " SCENE-DATA RAYSTATES OUTPUT OUTPUT-FINISHED" << endl;
}

vector<shared_ptr<Light>> loadLights() {
    vector<shared_ptr<Light>> lights;
    auto reader = global::manager.GetReader(ObjectType::Lights);

    while (!reader->eof()) {
        protobuf::Light proto_light;
        reader->read(&proto_light);
        lights.push_back(move(light::from_protobuf(proto_light)));
    }

    return lights;
}

shared_ptr<Sampler> loadSampler() {
    auto reader = global::manager.GetReader(ObjectType::Sampler);
    protobuf::Sampler proto_sampler;
    reader->read(&proto_sampler);
    return sampler::from_protobuf(proto_sampler);
}

Scene loadFakeScene() {
    auto reader = global::manager.GetReader(ObjectType::Scene);
    protobuf::Scene proto_scene;
    reader->read(&proto_scene);
    return from_protobuf(proto_scene);
}

enum class Operation { Trace, Shade };

int main(int argc, char const *argv[]) {
    try {
        if (argc <= 0) {
            abort();
        }

        if (argc != 5) {
            usage(argv[0]);
            return EXIT_FAILURE;
        }

        /* CloudBVH checks this */
        PbrtOptions.nThreads = 1;

        const string scenePath{argv[1]};
        const string raysPath{argv[2]};
        const string outputPath{argv[3]};
        const string finishedPath{argv[4]};

        global::manager.init(scenePath);

        vector<RayState> rayStates;
        vector<RayState> outputRays;
        vector<RayState> finishedRays;

        /* loading all the rays */
        {
            protobuf::RecordReader reader{raysPath};
            while (!reader.eof()) {
                protobuf::RayState protoState;
                if (reader.read(&protoState)) {
                    rayStates.push_back(move(from_protobuf(protoState)));
                }
            }
        }

        cerr << rayStates.size() << " RayState(s) loaded." << endl;

        if (!rayStates.size()) {
            return EXIT_SUCCESS;
        }

        MemoryArena arena;
        auto treelet = make_shared<CloudBVH>();
        auto sampler = loadSampler();
        auto lights = loadLights();
        auto fakeScene = loadFakeScene();

        for (auto & light : lights) {
            light->Preprocess(fakeScene);
        }

        for (auto &rayState : rayStates) {
            if (!rayState.toVisit.empty()) {
                auto newRay = CloudIntegrator::Trace(move(rayState), treelet);
                if (!newRay.isShadowRay || !newRay.hit.initialized()) {
                    outputRays.push_back(move(newRay));
                }
            } else if (rayState.isShadowRay) {
                if (!rayState.hit.initialized()) {
                    finishedRays.push_back(move(rayState));
                }
            } else if (rayState.hit.initialized()) {
                auto newRays = CloudIntegrator::Shade(move(rayState), treelet,
                                                      lights, sampler, arena);
                for (auto &newRay : newRays) {
                    outputRays.push_back(move(newRay));
                }
            }
        }

        /* writing all the output rays */
        {
            protobuf::RecordWriter writer{outputPath};
            for (auto &rayState : outputRays) {
                writer.write(to_protobuf(rayState));
            }
        }

        /* writing all the finished rays */
        {
            protobuf::RecordWriter writer{finishedPath};
            for (auto &rayState : finishedRays) {
                writer.write(to_protobuf(rayState));
            }
        }

        cerr << outputRays.size() << " output ray(s) and "
             << finishedRays.size() << " finished ray(s) were written." << endl;
    } catch (const exception &e) {
        print_exception(argv[0], e);
        return EXIT_FAILURE;
    }

    return EXIT_SUCCESS;
}
