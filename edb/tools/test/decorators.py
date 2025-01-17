#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2016-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


from __future__ import annotations

import unittest


skip = unittest.skip


def _xfail(reason, *, unless=False, allow_failure):
    def decorator(test_item):
        if unless:
            return test_item
        else:
            test_item.__et_xfail_reason__ = reason
            test_item.__et_xfail_allow_failure__ = allow_failure
            return unittest.expectedFailure(test_item)

    return decorator


def xfail(reason, *, unless=False):
    return _xfail(reason, unless=unless, allow_failure=True)


def xerror(reason, *, unless=False):
    return _xfail(reason, unless=unless, allow_failure=False)


def not_implemented(reason):
    def decorator(test_item):
        test_item.__et_xfail_reason__ = reason
        test_item.__et_xfail_not_implemented__ = True
        test_item.__et_xfail_allow_failure__ = True
        return unittest.expectedFailure(test_item)

    return decorator


def experimental_interpreter_exclude(msg = None):
    """
    This test case addresses a deficiency in the implementation but the experimental interpreter offers such features
    """

    def decorator(method):
        def wrapper(*args, **kwargs):
            if (hasattr(args[0], "use_experimental_interpreter")
                and args[0].use_experimental_interpreter):
                raise unittest.SkipTest(
                    'experimental interpreter: test excluded', msg)
            else:
                return method(*args, **kwargs)
        return wrapper
    return decorator

class ExperimentalInterpreterFeatureOrBugPending(Exception):
    pass

def experimental_interpreter_triaged_pending_feature(msg):
    """
    This is a feature that is not yet implemented in the experimental interpreter, 
    or is not sure whether this is the feature to implement
    """

    def decorator(method):
        def wrapper(*args, **kwargs):
            if (hasattr(args[0], "use_experimental_interpreter")
                and args[0].use_experimental_interpreter):
                # raise ExperimentalInterpreterFeatureOrBugPending(msg)
                raise unittest.SkipTest("PENDING FEATURE OR BUG: " + msg)
            else:
                return method(*args, **kwargs)
        return wrapper
    return decorator

class ExperimentalInterpreterBugPendingFix(Exception):
    pass

def experimental_interpreter_bug_pending_fix(msg):
    """
    This is clearly a bug pending fix

    """

    def decorator(method):
        def wrapper(*args, **kwargs):
            if (hasattr(args[0], "use_experimental_interpreter")
                and args[0].use_experimental_interpreter):
                # raise ExperimentalInterpreterFeatureOrBugPending(msg)
                raise unittest.SkipTest("PENDING BUG FIX: " + msg)
            else:
                return method(*args, **kwargs)
        return wrapper
    return decorator
