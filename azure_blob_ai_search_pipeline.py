import os
import logging
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    _edm as edm,
    SearchIndexerDataSourceConnection,
    SearchIndexer,
    IndexingSchedule
)
from azure.search.documents.indexes.models import SearchIndexerDataSourceType
from azure.search.documents import SearchClient

class AzureBlobAISearchPipeline:
    def __init__(self, index_name: str, data_source_name: str, indexer_name: str, logger: any) -> None:
        load_dotenv()
        # Replace with your Azure Search service name and admin key
        self.service_name = os.environ['AZURE_COGNITIVE_SEARCH_SERVICE_NAME']
        self.search_service_url = os.environ['AZURE_COGNITIVE_SEARCH_URL']
        self.admin_key = os.environ['AZURE_COGNITIVE_SEARCH_KEY']

        # Replace with your blob storage account name, connection string, and container name
        self.storage_account_name = os.environ['AZURE_STORAGE_ACCOUNT_NAME']
        self.storage_connection_string = os.environ['AZURE_STORAGE_BLOB_URL']
        self.container_name = os.environ['AZURE_CONTAINER_NAME']
        self.container_datasource_url = os.environ['AZURE_DATASOURCE_BLOB_STORAGE_URL']

        self.logger = logger
        
        if isinstance(index_name, (str, int)) and index_name != '':
            self.index_name = str(index_name)
        else:
            self.logger.error('Index name must be an str or int')
            ValueError('Index name must be an str or int')

        if isinstance(data_source_name, (str, int)) and data_source_name != '':
            self.data_source_name = str(data_source_name)
        else:
            self.logger.error('Data source name must be an str or int')
            ValueError('Data source name must be an str or int')

        if isinstance(index_name, (str, int)) and index_name != '':
            self.indexer_name = str(indexer_name)
        else:
            self.logger.error('Indexer name must be an str or int')
            ValueError('Indexer name must be an str or int')
        self.search_client_index_creator = SearchIndexClient(self.search_service_url, AzureKeyCredential(self.admin_key))
        self.indexer_client = SearchIndexerClient(self.search_service_url, AzureKeyCredential(self.admin_key))
        self.logger.info('Intialization done successfully')

    
    def __get_searchclient(self) -> SearchClient:
        return SearchClient(endpoint=self.search_service_url, index_name=self.index_name, credential=AzureKeyCredential(self.admin_key))

    def __list_indexes(self) -> list[any]:
        return self.search_client_index_creator.list_indexes()
    
    def get_indexerclient(self) -> SearchIndexerClient:
        return self.indexer_client
    
    def create_index(self) -> None:
        self.logger.info('Trying to create an index...')
        try:
            # Fields Can be made customisable. These are for example and this current application
            fields = [
                SimpleField(name="id", type=edm.String, key=True),
                SimpleField(name="metadata_storage_path", type=edm.String),
                SearchableField(name="content", type=edm.String, searchable=True),
            ]
            index = SearchIndex(name=self.index_name, fields=fields)
            
            self.logger.info(self.search_client_index_creator.create_index(index))
            self.logger.info(f'Index Created successfully by name {self.index_name}.')
        except Exception as e:
            self.logger.warn(f'The index by name {self.index_name} might be present. Stopping the creation of index with error {type(e).__name__}.')

    def create_indexer(self) -> None:
        self.logger.info('Trying to create an indexer...')
        try:
            indexer = SearchIndexer(
                name=self.indexer_name,
                data_source_name=self.data_source_name,
                target_index_name=self.index_name,
                schedule=IndexingSchedule(interval="PT2H")
                
            )
            self.logger.info(self.indexer_client.create_indexer(indexer))
            self.logger.info(f'Indexer Created successfully by name {self.indexer_name}.')
        except Exception as e:
            self.logger.warn(f'The Indexer by name {self.indexer_name} might be present. Stopping the creation of indexer with error {type(e).__name__}.')

    def create_datasource(self) -> None:
        self.logger.info('Trying to create an datasource...')
        try:
            # type can be customizable but this example uses Azure Blob Storage
            data_source = SearchIndexerDataSourceConnection(
                name=self.data_source_name,
                type=SearchIndexerDataSourceType.AZURE_BLOB,
                connection_string=self.container_datasource_url,
                container={"name": self.container_name})
            
            self.logger.info(self.indexer_client.create_data_source_connection(data_source))
            self.logger.info(f'Datasource Created successfully by name {self.data_source_name}.')
        except Exception as e:
            self.logger.warn(f'The datasource by name {self.data_source_name} might be present. Stopping the creation of datasource with error {type(e).__name__}.')


    def run_indexer(self) -> None:
        try:
            self.indexer_client.run_indexer(self.indexer_name)
            self.logger.info('Indexer Ran successfully')
            self.logger.warn('Indexer is on a cooldown of 180 seconds. For this tier')
        except Exception as e:
            self.logger.error(e)


    def run_query(self, query_text: str) -> list[dict]:
        try:
            self.logger.info('Triggering the search client')
            results = self.__get_searchclient().search(query_text)
            self.logger.info('Query ran successfully, returing the results')
            return results
        except Exception as e:
            self.logger.error(e)

def trigger_pipeline(index_name:str, data_source_name:str, indexer_name:str, query_text: str) -> list[dict]:
    # Initialize logger
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename=f'{os.path.abspath(os.path.curdir)}/logs/app.log')
    logger = logging.getLogger(__name__)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logger.info('Pipeline Triggered')

    azure_blob_indexer_pipeline = AzureBlobAISearchPipeline(
        logger=logger,
        data_source_name=data_source_name,
        index_name=index_name,
        indexer_name=indexer_name
    )

    azure_blob_indexer_pipeline.create_index()
    azure_blob_indexer_pipeline.create_datasource()
    azure_blob_indexer_pipeline.create_indexer()

    azure_blob_indexer_pipeline.run_indexer()

    results = azure_blob_indexer_pipeline.run_query(query_text=query_text)
    
    return results
    

if __name__ == '__main__':
    results = trigger_pipeline(
        data_source_name='pipeline-blob-datasource',
        index_name='pipeline-blob-index',
        indexer_name='pipeline-blob-indexer',
        query_text='svd')

    for item in results:
        print(item)
