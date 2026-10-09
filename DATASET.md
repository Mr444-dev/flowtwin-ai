# Dataset notes: BPI Challenge 2017

## Source and scope

FlowTwin uses the **BPI Challenge 2017** event log published by Boudewijn F. van Dongen through 4TU.ResearchData. The dataset describes online loan applications submitted in 2016 to a financial institution in the Netherlands, with recorded events through **1 February 2017 at 15:11**. The source describes a process system that supports multiple offers per application.

The 4TU record is the authoritative download and citation page: [BPI Challenge 2017 dataset](https://data.4tu.nl/articles/dataset/BPI_Challenge_2017/12696884). The [Eindhoven University of Technology research portal](https://research.tue.nl/en/datasets/bpi-challenge-2017/) provides a searchable metadata record. A [published BPI Challenge analysis](https://ais.win.tue.nl/bpi/2017/bpi2017_paper_15.pdf) reports **1,202,267 events across 31,509 cases**; these are source-reported counts, not counts produced or independently verified by this repository.

> van Dongen, B. F. (2017). *BPI Challenge 2017*. 4TU.ResearchData. [https://doi.org/10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b](https://doi.org/10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b)

## How this project uses the log

- One XES trace is treated as one application case. Offer and workflow records remain events inside that trace; this unit-of-analysis assumption should be checked against the source log before interpreting results.
- The parser retains completed lifecycle events when lifecycle data is present, normalizes timestamps to UTC, and records data-quality counts.
- Regression targets are built only for traces whose last event matches the project's explicit terminal-activity heuristic and which contain a forecastable prefix. This is a selected completed-case population, not a time-to-resolution estimate for all applications.
- The forecast target is elapsed calendar time to the last observed terminal event. It includes queue, customer-wait, night, and weekend time; it is not active staff time, an SLA, or the bank's operational definition of completion.
- This is historical process data. It says nothing by itself about current banking operations, causes of delays, or the effect of interventions.

## Download, integrity, and reuse

The `flowtwin download` command retrieves the compressed event log from the 4TU file endpoint and checks the configured MD5 checksum (`10b37a2f78e870d78406198403ff13d2`) before saving it under `data/raw/`. This checksum detects accidental corruption and identifies the expected file; it is not a cryptographic authenticity guarantee.

The source dataset is not bundled with this repository and should not be committed here. Review the current 4TU record, citation requirements, and reuse terms before redistributing the data or using it beyond a portfolio or academic demonstration. This repository does not claim ownership of the dataset or impose its software license on the data.

## Validation status

The code has not yet been run end to end on the original dataset in this environment. No real-data training metric, dashboard count, or data-quality result is claimed here. After downloading the source, run `flowtwin download`, `flowtwin prepare`, and `flowtwin train`; inspect `reports/generated/metrics.json` and `reports/generated/test_predictions.csv`, then validate the completion and attribute-timing assumptions before presenting model results.
