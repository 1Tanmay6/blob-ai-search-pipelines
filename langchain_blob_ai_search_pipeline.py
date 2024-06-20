import os
import uuid
import logging
import sqlite3
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from azure.search.documents.indexes import SearchIndexClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    _edm as edm
)
from langchain_community.document_loaders import UnstructuredFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

class LangchainBlobAISearch:
    def __init__(self, index_name: str) -> None:
        load_dotenv()
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', filename=f'{os.path.abspath(os.path.curdir)}/logs/langchain_chunker_blob_app.log')
        self.logger = logging.getLogger(__name__)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        self.__create_sqlite_database()
        self.connection_string = os.environ['AZURE_STORAGE_CONNECTION_STRING']
        self.container_name = os.environ['AZURE_CONTAINER_NAME']
        service_name = os.environ['AZURE_COGNITIVE_SEARCH_SERVICE_NAME']
        admin_key = os.environ['AZURE_COGNITIVE_SEARCH_KEY']
        self.logger.info('Creating a Blob Service Client with the provided connection string.')
        self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
        self.container_client = self.blob_service_client.get_container_client(self.container_name)
        self.logger.info('Created Blob Service Client')
        if isinstance(index_name, (str, int)) and index_name != '':
            self.index_name = str(index_name)
        else:
            self.logger.error('Index name must be an str or int')
            ValueError('Index name must be an str or int')
        credential = AzureKeyCredential(admin_key)
        endpoint = f"https://{service_name}.search.windows.net"
        self.logger.info('Creating a Search Client with the provided connection string.')
        self.search_client = SearchClient(endpoint, self.index_name, credential)
        self.search_index_client = SearchIndexClient(endpoint, credential)
        self.logger.info('Creating a Search Client.')
        self.logger.info('Initialization successfully Completed')

    def __get_blobs_list(self) -> iter:
        return self.container_client.list_blobs()
    
    def __get_file_name(self, type: str) -> str:
        folder_path = f'temp/{type}'
        files = os.listdir(folder_path)
        file_paths = [os.path.join(folder_path, file) for file in files if os.path.isfile(os.path.join(folder_path, file))]
        return file_paths[0]

    def __pdf_to_text(self) -> None:
        self.logger.info('Starting the text extractor')
        loader = UnstructuredFileLoader(self.__get_file_name(type='blob'))
        self.logger.info(f'Extracting from file {self.__get_file_name(type='blob')}')
        docs = loader.load()
        with open('temp/txt/temp.txt', 'w') as f:
            f.write(docs[0].page_content)
        self.logger.info(f'Extraction Completed for file {self.__get_file_name(type='blob')}')

    def __chunk_text(self, chunk_size: int = 2048, overlap: int = 256) -> list:
        with open(self.__get_file_name(type='txt'), 'r') as f:
            full_text = f.read()
        self.logger.info('Starting the chunker')
        splitter = RecursiveCharacterTextSplitter(separators=['\n', ' ', '.'], chunk_size=chunk_size, chunk_overlap=overlap)
        chunks = splitter.split_text(full_text)
        self.logger.info(f"Chunked Successfully for file {self.__get_file_name(type='txt')}")
        return chunks

    def __create_sqlite_database(self) -> None:
        if not os.path.exists("database"):
            os.makedirs("database")
        db_path = os.path.join("database", "file_check_in.db")
        self.logger.info(f'Checking for the availablity of the database at {db_path}')

        if os.path.exists(db_path):
            self.logger.warn(f"Database '{db_path}' already exists. Exiting the function.")
            return
        
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            self.logger.info('Creating a persistent table')
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS checked_files (
                    id INTEGER PRIMARY KEY,
                    file_name TEXT
                )
            """)
            
            self.logger.info(f"Database created at: {db_path}, along with table.")

        except sqlite3.Error as e:
            self.logger.error(f"Failed to create database or table: {e}")

        finally:
            conn.close()
            self.logger.info('Closing the connection with the database.')

    def __insert_new_file_into_db(self, file_name: str) -> None:
        try:
            conn = sqlite3.connect("database/file_check_in.db")
            cursor = conn.cursor()
            cursor.execute("INSERT INTO checked_files (file_name) VALUES (?)", (file_name,))
            conn.commit()
        except Exception as e:
            self.logger.error(f'Failed to insert the file: {e}')
        finally:
            conn.close()

    def __check_availablity(self, file_name: str) -> bool:
        try:
            conn = sqlite3.connect("database/file_check_in.db")
            cursor = conn.cursor()
            results = cursor.execute(
                """SELECT * FROM checked_files WHERE file_name == (?)""", (file_name,)
            ).fetchall()
            if len(results) > 0:
                return False
            else:
                return True
        except Exception as e:
            self.logger.error(f'Failed to check availablity: {e}')
        finally:
            conn.close()


    def __upload_documents(self, documents: list[dict]) -> None:
        try:
            self.search_client.upload_documents(documents)
        except Exception as e:
            self.logger.error(f'Failed uploading of documents: {e}')

    def __document_generator(self, chunks: list, file_name: str) -> list[dict]:
        try:
            documents = []
            self.logger.info('Generating documents for the chunks')
            for chunk in chunks:
                unique_id = uuid.uuid1()
                documents.append({"id": str(unique_id).split('-')[0], "content": chunk, "metadata_storage_path": file_name})
                self.logger.info('Generation of documents successfully completed.')
            return documents
        except Exception as e:
            self.logger.error(f'Failed generation of documents: {e}')
            return []

    def trigger_pipeline(self) -> None:
        self.logger.info('Pipeline Triggered')
        blobs = self.__get_blobs_list()
        for blob in blobs:
            if self.__check_availablity(file_name=blob.name):
                self.logger.info(f'Intializing process for {blob.name}')
                blob_client = self.container_client.get_blob_client(blob.name)
                blob_content = blob_client.download_blob().readall()
                with open(f'temp/blob/{blob.name.split('/')[-1]}', 'wb') as f:
                    f.write(blob_content)
                self.__pdf_to_text()
                chunks = self.__chunk_text()
                docs = self.__document_generator(chunks=chunks, file_name=blob.name)
                self.logger.info('Uploading documents to the AI search')
                self.__upload_documents(documents=docs)
                self.__insert_new_file_into_db(file_name=blob.name)
                os.remove(f'temp/blob/{blob.name.split('/')[-1]}')
            else:
                self.logger.warn(f'{blob.name} has already been processed')

    def create_index(self) -> None:
        self.logger.info('Trying to create an index...')
        try:
            fields = [
                    SimpleField(name="id", type=edm.String, key=True),
                    SearchableField(name="content", type=edm.String, searchable=True),
                    SimpleField(name="metadata_storage_path", type=edm.String),
                ]
            index = SearchIndex(name=self.index_name, fields=fields)
            self.search_index_client.create_index(index)
            self.logger.info(f'Index Created successfully by name {self.index_name}.')
        except Exception as e:
            self.logger.error(f'The index by name {self.index_name} might be present. Stopping the creation of index with error {type(e).__name__}.')

    def run_query(self) -> list[dict]:
        try:    
            self.logger.info('Triggering the search client')
            results = self.search_client.search("luxury hotel")
            self.logger.info('Query ran successfully, returing the results')
        
            return results
        except Exception as e:
            self.logger.error(e)

if __name__ == '__main__':
    lang = LangchainBlobAISearch(index_name='langchain-pipeline-index')
    lang.create_index()
    lang.trigger_pipeline()
