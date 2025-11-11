.PHONY: venv install install-dev test run clean interfaces docs

VENV?=./.venv
PYTHON=${VENV}/bin/python3

CONTRACTS := $(shell find contracts -maxdepth 2 -name '*.vy' | grep -v auxiliary)
NATSPEC := $(patsubst contracts/%, natspec/%, $(CONTRACTS:%.vy=%.json))
PATH := ${VENV}/bin:${PATH}
PYTHONPATH:=contracts:scripts:$(PYTHONPATH)

vpath %.vy ./contracts

$(VENV):
	if ! command -v uv > /dev/null; then python -m pip install -U uv; fi
	uv venv $(VENV)

install: ${VENV} requirements.txt
	uv pip sync requirements.txt

install-dev: $(VENV) requirements-dev.txt
	uv pip sync requirements-dev.txt
	$(VENV)/bin/pre-commit install

requirements.txt: pyproject.toml
	uv pip compile -o requirements.txt pyproject.toml

requirements-dev.txt: pyproject.toml
	uv pip compile -o requirements-dev.txt --extra dev pyproject.toml

test: ${VENV}
	${VENV}/bin/pytest tests

coverage:
	${VENV}/bin/coverage run -m pytest tests/up2p_erc20_v2/nit --runslow
	${VENV}/bin/coverage report

branch-coverage:
	${VENV}/bin/coverage run --branch -m pytest tests/p2p_erc20_v2/unit --runslow
	${VENV}/bin/coverage report

unit-tests:
	${VENV}/bin/pytest tests/p2p_erc20_v1/unit tests/p2p_erc20_v2/unit --runslow -n auto --dist loadscope

integration-tests:
	${VENV}/bin/pytest tests/p2p_erc20_v1/integration tests/p2p_erc20_v2/integration

profitr-tests:
	${VENV}/bin/pytest tests/p2p_erc20_v2/profitr

gas:
	${VENV}/bin/pytest tests/p2p_erc20_v2/unit --gas-profile

interfaces:
	${VENV}/bin/python scripts/build_interfaces.py contracts/*.vy

docs: $(NATSPEC)

natspec/%.json: %.vy
	dirname $@ | xargs mkdir -p && ${VENV}/bin/vyper -f userdoc,devdoc $< > $@

clean:
	rm -rf ${VENV} .cache .build __pycache__ **/__pycache__

lint:
	$(VENV)/bin/ruff check --select I --fix .
	$(VENV)/bin/ruff format tests scripts

%-local: export ENV=local
%-dev: export ENV=dev
%-int: export ENV=int
%-prod: export ENV=prod

%-zethereum %-zapechain: export ENV=dev
%-sepolia %-curtis: export ENV=int
%-ethereum %-apechain: export ENV=prod

%-local: export CHAIN=foundry
%-zethereum: export CHAIN=zethereum
%-zapechain: export CHAIN=zapechain
%-sepolia: export CHAIN=sepolia
%-curtis: export CHAIN=curtis
%-ethereum: export CHAIN=ethereum
%-apechain: export CHAIN=apechain

%-local: export NETWORK=ethereum:local:foundry
%-zethereum: export NETWORK=ethereum:local:https://network.dev.zharta.io/dev1/
%-zapechain: export NETWORK=ethereum:local:https://network.dev.zharta.io/dev2/

%-sepolia: export NETWORK=ethereum:sepolia:alchemy
%-curtis: export NETWORK=apechain:curtis:https://curtis.rpc.caldera.xyz/http
%-ethereum: export NETWORK=ethereum:mainnet:alchemy
%-apechain: export NETWORK=apechain:mainnet:alchemy

add-account:
	${VENV}/bin/ape accounts import $(alias)

compile:
	rm -rf .build/*
	${VENV}/bin/ape compile

console-local console-zethereum console-zapechain console-sepolia console-curtis console-ethereum console-apechain:
	${VENV}/bin/ape console --network ${NETWORK} # --verbosity DEBUG

deploy-local deploy-zethereum deploy-zapechain deploy-sepolia deploy-curtis deploy-ethereum deploy-apechain:
	${VENV}/bin/ape run -I deployment --network ${NETWORK}

publish-zethereum publish-zapechain publish-sepolia publish-curtis publish-ethereum publish-apechain:
	${VENV}/bin/ape run publish

get-metadata-zethereum get-metadata-zapechain get-metadata-sepolia get-metadata-curtis get-metadata-ethereum get-metadata-apechain:
	${VENV}/bin/ape run get_tokens
