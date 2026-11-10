# 0009. YAML input with time-based post variations

**Status:** Accepted. Shift generation detailed by [0018](0018-slot-generation-by-segments.md).

## Context

TinyScheg needs to read a description of the schedule period, the workers and the posts. Posts often have
different requirements at different times of day, e.g. more workers at night. An earlier iteration of the project
read workers and jobs from two separate files.

## Decision

* Input is a **single YAML file** with three sections: `settings`, `workers` and `posts`.
  See [Input format](../reference/input-format.md).
* Fields other than names may be omitted and are then considered empty.
* Posts specify required roles with a count per role (`any` being a wildcard). The total number of workers per
  shift isn't specified separately, since it's the sum of the role counts.
* Posts may have **variations**: recurring daily time windows that override the post's roles and shift length.
  Fields a variation doesn't specify are inherited from the post's general case.

## Consequences

* Input is human-readable and easy to write by hand.
* Parsing must convert daily time windows (including ones that cross midnight) into concrete date-time ranges over
  the schedule period, and fill in inherited variation fields, before constructing `Post` objects.
