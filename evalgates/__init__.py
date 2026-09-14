# the harness. it talks to the scoring service over its http contract and
# never imports sut internals - if the service is broken, the harness must
# see what a real caller would see.
