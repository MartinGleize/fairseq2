// Copyright (c) Meta Platforms, Inc. and affiliates.
// All rights reserved.
//
// This source code is licensed under the BSD-style license found in the
// LICENSE file in the root directory of this source tree.

#include "fairseq2n/data/map_data_source.h"

#include <exception>

#include "fairseq2n/data/data_pipeline.h"
#include "fairseq2n/data/detail/exception.h"
#include "fairseq2n/detail/parallel.h"

namespace fairseq2n::detail {

map_data_source::map_data_source(
    std::unique_ptr<data_source> &&inner,
    std::vector<map_fn> &&fns,
    std::size_t num_parallel_calls,
    bool deterministic)
  : inner_{std::move(inner)},
    map_fns_{std::move(fns)},
    num_parallel_calls_{num_parallel_calls},
    deterministic_{deterministic || num_parallel_calls == 1},
    pool_{deterministic ? 0 : num_parallel_calls}
{
    buffer_.reserve(num_parallel_calls);

    buffer_pos_ = buffer_.begin();
}

std::optional<data>
map_data_source::next()
{
    if (num_parallel_calls_ <= 1) {
        while (std::optional<data> maybe_example = inner_->next()) {
            maybe_example = invoke_function(*std::move(maybe_example), 0);
            if (maybe_example)
                return maybe_example;
        }

        return std::nullopt;
    }

    if (deterministic_) {
        do {
            // Yield a buffered example.
            for (; buffer_pos_ < buffer_.end(); ++buffer_pos_) {
                if (*buffer_pos_)
                    return std::move(*buffer_pos_++);
            }
        // If we have exhausted all buffered examples, try to refill the buffer.
        } while (fill_buffer());
    } else {
        // Check that we either have work or waiting outputs
        while (fill_buffer_async()) {
            // Wait until the next output is ready
            std::unique_lock<std::mutex> lock{async_output_mutex_};
            read_output_condition_.wait(lock, [this]
            {
                return !async_queue_.empty() || exception_ptr_;
            });

            if (exception_ptr_)
                std::rethrow_exception(exception_ptr_);

            auto example = std::move(async_queue_.front());
            async_queue_.pop_front();
            if (example)
                return example;
        }
    }

    return std::nullopt;
}

void
map_data_source::reset(bool reset_rng)
{
    buffer_.clear();

    buffer_pos_ = buffer_.begin();
    
    reset_async_state();

    async_queue_.clear();

    inner_->reset(reset_rng);
}

void
map_data_source::record_position(tape &t, bool strict) const
{
    if (strict) {
        if (deterministic_) {
            t.record(buffer_);

            t.record(buffer_pos_ - buffer_.begin());
        } else {
            // Wait until all current tasks have output to the queue
            wait_until_done();
            // Write the queue on the tape
            {
                std::unique_lock<std::mutex> lock{async_output_mutex_};
                t.record(async_queue_.size());

                for (const auto &element : async_queue_)
                    t.record(element);
            }
        }
    }

    inner_->record_position(t, strict);
}

void
map_data_source::reload_position(tape &t, bool strict)
{
    if (strict && deterministic_) {
        buffer_ = t.read<std::vector<std::optional<data>>>();

        buffer_pos_ = buffer_.begin() + t.read<std::ptrdiff_t>();
    } else if (strict && !deterministic_) {
        // Wait for all tasks to complete and reset state
        reset_async_state();

        async_queue_.clear();

        // Fill the queue again from the tape
        std::size_t size = t.read<std::size_t>();
        for (std::size_t i = 0; i < size; ++i)
            async_queue_.push_back(t.read<std::optional<data>>());

        buffer_.clear();
        buffer_pos_ = buffer_.begin();
    } else {
        buffer_.clear();

        buffer_pos_ = buffer_.begin();

        reset_async_state();

        async_queue_.clear();
    }

    inner_->reload_position(t, strict);
}

data_source_finitude_type
map_data_source::finitude_type() const noexcept
{
    return inner_->finitude_type();
}

bool
map_data_source::fill_buffer()
{
    buffer_.clear();

    for (std::size_t i = 0; i < num_parallel_calls_; i++) {
        std::optional<data> maybe_example = inner_->next();
        if (!maybe_example)
            break;

        buffer_.push_back(std::move(maybe_example));
    }

    if (buffer_.empty())
        return false;

    // Apply the processor to all buffered examples.
    auto apply_function = [this](std::size_t begin, std::size_t end)
    {
        for (auto i = begin; i < end; ++i)
            buffer_[i] = invoke_function(*std::move(buffer_[i]), i);
    };

    // Avoid threading overhead if we have just one example.
    if (buffer_.size() == 1)
        apply_function(0, buffer_.size());
    else
        parallel_for<std::size_t>(apply_function, buffer_.size());

    buffer_pos_ = buffer_.begin();

    return true;
}

bool
map_data_source::has_async_output()
{
    std::unique_lock<std::mutex> lock(async_output_mutex_);
    return !async_queue_.empty();
}

void
map_data_source::reset_async_state()
{
    wait_until_done();

    finished_ = false;
}

void
map_data_source::wait_until_done() const
{
    std::unique_lock<std::mutex> lock{async_output_mutex_};
    read_output_condition_.wait(lock, [this]
    {
        return tasks_in_flight_ == 0 || exception_ptr_;
    });

    if (exception_ptr_)
        std::rethrow_exception(exception_ptr_);
}

bool
map_data_source::fill_buffer_async()
{
    for (std::size_t i = tasks_in_flight_; i < num_parallel_calls_; i++) {
        std::optional<data> maybe_example = inner_->next();
        if (!maybe_example) {
            finished_ = true;
            break;
        }

        tasks_in_flight_++;

        // Create task and send to thread pool
        data example = std::move(*maybe_example);

        auto apply_function = [this](data&& ex)
        {
            try {
                // Compute the function (the first one)
                data result = map_fns_[0](std::move(ex));
                // Add to output queue
                {
                    std::unique_lock<std::mutex> lock(async_output_mutex_);
                    async_queue_.push_back(std::move(result));
                }
            } catch (const std::exception &) {
                std::unique_lock<std::mutex> lock(async_output_mutex_);
                exception_ptr_ = std::current_exception();
            }
            
            tasks_in_flight_--;
            read_output_condition_.notify_one();
        };
        
        pool_.enqueue(apply_function, std::move(example));
    }

    return !finished_ || tasks_in_flight_ > 0 || has_async_output();
}

std::optional<data>
map_data_source::invoke_function(data &&example, std::size_t fn_idx)
{
    return map_fns_[fn_idx](std::move(example));
}

}  // namespace fairseq2n::detail
