# lnapgdb
Postgresql database for LNA observations

# TODO

- [ ] Create the database manager, which should be able to gather the new images from within a set of directories (whose could be defined in a config file)
- [ ] Decide if we go for a config file or if we just use environment variables to set the directories to be monitored
- [ ] The manager must be able to handle a large number of directories and images within
- [ ] The code needs to keep track of the images that have already been processed
- [ ] The list of new images at any given moment should be handled to the data_collector.py, which will extract the metadata, validate them and return as a pandas df
- [ ] Finally, the manager haddles the df to the insertdb.py module for database insertion
