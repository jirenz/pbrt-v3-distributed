#ifndef PBRT_UTIL_RANDOM_H
#define PBRT_UTIL_RANDOM_H

#include <iterator>
#include <random>

namespace pbrt {
namespace random {

template <typename Iter, typename RandomGenerator>
Iter sample(Iter start, Iter end, RandomGenerator& g) {
    std::uniform_int_distribution<> dis(0, std::distance(start, end) - 1);
    std::advance(start, dis(g));
    return start;
}

template <typename Iter>
Iter sample(Iter start, Iter end) {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    return sample(start, end, gen);
}

}  // namespace random
}  // namespace pbrt

#endif /* PBRT_UTIL_RANDOM_H */
