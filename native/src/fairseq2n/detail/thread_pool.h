// Copyright (c) Meta Platforms, Inc. and affiliates.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#pragma once

#include <vector>
#include <queue>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <functional>
#include <memory>

namespace fairseq2n::detail {

class thread_pool {
public:
    explicit
    thread_pool(size_t num_threads) : num_threads_(num_threads), stop_(false) {
        workers_.reserve(num_threads_);

        for (size_t i = 0; i < num_threads_; ++i) {
            workers_.emplace_back([this] {
                while (true) {
                    std::function<void()> task;
                    {
                        std::unique_lock<std::mutex> lock(queue_mutex_);
                        queued_condition_.wait(lock, [this] {
                            return stop_ || !tasks_.empty();
                        });
                        
                        if (stop_ && tasks_.empty()) {
                            return;
                        }

                        task = std::move(tasks_.front());
                        tasks_.pop();
                    }
                    task();
                }
            });
        }
    }
    
    template<class F, class... Args>
    void
    enqueue(F&& f, Args&&... args) {
        auto task = std::make_shared<std::tuple<std::decay_t<F>, std::decay_t<Args>...>>(
            std::forward<F>(f), std::forward<Args>(args)...);
        
        {
            std::unique_lock<std::mutex> lock(queue_mutex_);
            if (stop_) {
                throw std::runtime_error("Cannot enqueue on stopped ThreadPool");
            }
            
            tasks_.emplace([task]() {
                std::apply(std::move(std::get<0>(*task)), 
                    [&task]() {
                        return std::tuple<Args...>(std::move(std::get<Args>(*task))...);
                    }());
            });
        }
        queued_condition_.notify_one();
    }
    
    ~thread_pool() {
        {
            std::unique_lock<std::mutex> lock(queue_mutex_);
            stop_ = true;
        }
        queued_condition_.notify_all();
        
        for (std::thread& worker : workers_) {
            worker.join();
        }
    }

    // Delete copy constructor and assignment operator
    thread_pool(const thread_pool&) = delete;
    thread_pool& operator=(const thread_pool&) = delete;

private:
    size_t num_threads_;
    std::vector<std::thread> workers_;
    std::queue<std::function<void()>> tasks_;
    
    std::mutex queue_mutex_;
    std::condition_variable queued_condition_;
    bool stop_;
};

}
