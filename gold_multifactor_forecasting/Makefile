.PHONY: install profile base download merge test-london test-shanghai audit-london audit-shanghai smoke

install:
	python -m pip install -r requirements.txt

profile:
	python scripts/01_profile_raw_data.py

base:
	python scripts/02_build_base_datasets.py

download:
	python scripts/03_download_public_factors.py

merge:
	python scripts/04_merge_point_in_time.py

test-london:
	python scripts/05_run_all_factor_tests.py --market london --horizon 20

test-shanghai:
	python scripts/05_run_all_factor_tests.py --market shanghai --horizon 20

audit-london:
	python scripts/06_build_factor_audit.py --market london --horizon 20

audit-shanghai:
	python scripts/06_build_factor_audit.py --market shanghai --horizon 20

smoke:
	pytest -q
