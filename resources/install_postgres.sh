#!/bin/bash

# This script install PostgreSQL on linux systems including the dependencies
# It was tested on Debian 13 Trixie
# This script also sets up the pg_hba.conf and the postgresql.conf files with the
# necessary configuration for replication
#
# Usage: ./install_postgres.sh <node_type> <replication_user> <replication_password>
# Example: ./install_postgres.sh primary rep_user rep_password
#

NODE_TYPE=$1
REPLICATION_USER=$2
REPLICATION_PASSWORD=$3

# Find the linux distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO=$ID
    VERSION=$VERSION_ID
else
    echo "Unsupported Linux distribution"
    exit 1
fi

# Find the package manager
if command -v apt-get >/dev/null; then
    PACKAGE_MANAGER="apt-get"
elif command -v yum >/dev/null; then
    PACKAGE_MANAGER="yum"
elif command -v dnf >/dev/null; then
    PACKAGE_MANAGER="dnf"
  else
    echo "Unsupported package manager"
    exit 1
fi

# Install PostgreSQL and dependencies
install_postgres() {
    if [ "$PACKAGE_MANAGER" == "apt-get" ]; then
        sudo apt-get update
        sudo apt-get install -y postgresql postgresql-client postgresql-doc
        # install additional dependencies for replication
        sudo apt-get install -y postgresql-contrib openssl libssl-dev libpq5 libpq-dev python3-psycopg2 gcc make python3-dev

      elif [ "$PACKAGE_MANAGER" == "yum" ]; then
        sudo yum install -y postgresql-server postgresql-contrib
        # install additional dependencies for replication
        sudo yum install -y postgresql-devel openssl-devel python3-psycopg2 python3-devel

      elif [ "$PACKAGE_MANAGER" == "dnf" ]; then
        sudo dnf install -y postgresql-server postgresql-contrib
        # install additional dependencies for replication
        sudo dnf install -y postgresql-devel openssl-devel python3-psycopg2 python3-devel
    fi
}
install_postgres
echo "PostgreSQL installation completed."

# Postgres user access configuration
sudo su -c /usr/bin/psql postgres
exit

# Add a new user for replication
sudo adduser --disabled-password --gecos "" mypguser
sudo su - postgres
createuser --pwprompt mypguser
createdb -O mypguser lnapgdb
exit
sudo su -c /usr/bin/psql postgres
psql -c "CREATE ROLE mypguser WITH REPLICATION LOGIN ENCRYPTED PASSWORD $REPLICATION_PASSWORD;"
exit

# Configure pg_hba.conf for replication
# Get location of this script
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
# A copy of the pg_hba.conf and postgres.conf files are included in the upper level directory "credentials"
PG_HBA_CP="$SCRIPT_DIR/../credentials/pg_hba.conf"
POSTGRES_CONF_CP="$SCRIPT_DIR/../credentials/postgresql.conf"
# Get postgresql version
PG_VERSION=$(psql -V | awk '{print $3}' | cut -d '.' -f 1)
PG_HBA_DEST="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
sudo cp $PG_HBA_CP $PG_HBA_DEST
# Configure postgresql.conf for replication
PG_CONF_DEST="/etc/postgresql/$PG_VERSION/main/postgresql.conf"
sudo cp $POSTGRES_CONF_CP $PG_CONF_DEST
