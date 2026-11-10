Iris data: Fisher, R. (1936). Iris [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C56C76 · CC BY 4.0 · https://creativecommons.org/licenses/by/4.0/
Downloaded `bezdekIris.data` from the UCI Iris archive and stored unchanged as `iris.csv`.
TripSci converts it to JSON and creates a fixed stratified train/validation/test split.

Dry Bean data: Koklu, M., and Özkan, İ. A. (2020). Dry Bean [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C50S4B · CC BY 4.0 · https://creativecommons.org/licenses/by/4.0/
Source CSV: https://archive.ics.uci.edu/static/public/602/data.csv. Stored losslessly as gzip.
TripSci removes duplicate feature rows and excludes ambiguous labels before making a deterministic stratified 70%/15%/15% train/validation/holdout split.
