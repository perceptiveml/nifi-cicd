# Athena TO6 NiFi CI/CD Test Bed

This repo establishes a local test bed for developing and testing CI/CD operations between NiFi and NiFi Registry. There are a total of two environments within this test bed: DEV and TEST. Each environment is contained within its own network: dev-env and test-env.

Each environment contains three docker containers: one for zookeeper, nifi, and nifi-registry. Additionally, each environment requires a git repository where nifi flows will be stored and versioned. Environment variables are required for setting up NiFi Registry correctly (see prerequisites below). A Git Provider is configured automatically in the NiFi Registry providers.conf file based on the specified environment variables.

Within the python directory, this repo contains scripts for migrating Nifi process groups from the DEV to TEST environment using the Nifi Registry.

## Project Structure
```
nifi-cicd
├── python
|     |── migrate.py             # python script to promote nifi flows to higher environments
|     |── utils.py               # python script with utility functions to support migration operations
|     └── requirements.txt       # python packages required to run this project
├── README.md                    # project readme file
└── docker-compose.yml           # docker compose file for deploying and running the nifi test bed
```

## Pre-requisites
-   A git repository is required for each environment (GitHub) with proper user credentials (username, access password, etc.)
-   Ensure Docker is installed on your workstation (version 3.8)
  -   If using an older version of Docker, then ensure you change the version in the `docker-compose.yml` file
-   Ensure Python 3.7.x is installed on your workstation (https://python.org/)
      -   `pip3 install -r requirements.txt` to ensure you have all python packages installed

## Docker

To run this application using Docker Compose:

```bash
# build the docker compose
docker-compose build

# run the docker compose
docker-compose up -d

# tunnel into the container (if needed)
docker exec -it -u 0 <container_name> bash

# stop the container
docker-compose down

# stop the container and destroy volumes
docker-compose down -v
```

## NiFi Registry Settings
To complete the Registry setup, you need to create a Registry Bucket to act as a Container for the Flows that you will be pushing to the Registry. Click on the Spanner icon on the top right corner and select New Bucket. Enter a name for your bucket. Repeat this process for both Registry clients (dev, test).

## NiFi Settings
By default, Nifi does not point to any Registry component. You need to change this by adding a Registry Client so that Nifi knows that Flow definitions will be version controlled. To do this, navigate to the NiFi instance UI using a web browser. Go to the Settings menu (three lines on the top right corner) -> Controller Settings -> Registry Clients -> New Client (plus sign icon). Fill out the required fields. Note, the Registry URL should only be the host and the port (ex. http://nifi-registry-dev:18080), and not contain the the /nifi-registry path.

Create a sample ProcessGroup with a flow within the NiFi instance in the dev environment. When finished, right click on the ProcessGroup and select Version->Start version control.

## CI/CD Automation
A Python script is provided that will stage and migrate selected version controlled ProcessGroups in the dev environment to the specified test environment.
