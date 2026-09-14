# the system under test: a claim-frequency scorer and the service around it.
# the harness package (evalgates/) talks to the service over http like any
# other client and imports nothing from here, with one documented exception:
# runner.ServiceClient imports sut.app once, solely to host the service
# in-process for local runs. the separation is deliberate: a harness that
# reads the model's internals passes while the service is down.
