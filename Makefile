# the whole workflow, one target each. `make test gate` is what ci does.

.PHONY: test gate baseline serve report data fit clean

test:
	python -m pytest tests/ -q

gate:
	python -m evalgates.gate --suite suites/release_v1.yaml \
	  --baseline baseline.json \
	  --export out/testrail.json --report out/report.html

# run ONLY after a reviewed change that legitimately moves a metric
# (new model, new slice); the diff to baseline.json is the review artifact
baseline:
	python -m evalgates.gate --suite suites/release_v1.yaml \
	  --baseline baseline.json --save-baseline

serve:
	uvicorn sut.app:app --host 0.0.0.0 --port 8080

report:
	python -m evalgates.gate --suite suites/release_v1.yaml --report out/report.html

# re-pull the public data and re-cut the slices (needs requirements-fit.txt)
data:
	python data/fetch_fremtpl.py

# refit on the full extract and freeze coefficients (needs requirements-fit.txt)
fit:
	python -m sut.fit --data /tmp/fremtpl/fremtpl_indomain.csv.gz

clean:
	rm -rf out .evalgates .pytest_cache */__pycache__ */*/__pycache__
