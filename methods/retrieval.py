import numpy as np
import pandas as pd
from tqdm import tqdm

import os
import sys
nb_dir = os.path.split(os.getcwd())[0]
if nb_dir not in sys.path:
    sys.path.append(nb_dir)

from methods.baseline import Baseline
from keras.layers import Conv1D, Input, Add, Activation, Dropout, Embedding, \
        MaxPooling1D, GlobalMaxPool1D, Flatten, Dense, Concatenate, BatchNormalization
from keras.models import Model
from sklearn.neighbors import NearestNeighbors

class Retrieval():
    def __init__(self):
        pass
    
    def load_bugs(self, data, train):
        self.baseline.load_ids(data)
        self.baseline.prepare_dataset()
        self.baseline.load_bugs()

    def create_bucket(self, df):
        print("Creating the buckets...")
        buckets = {}
        # Reading the buckets
        df_buckets = df[df['dup_id'] == '[]']
        loop = tqdm(total=df_buckets.shape[0])
        for row in df_buckets.iterrows():
            name = row[1]['bug_id']
            buckets[name] = set()
            buckets[name].add(name)
            loop.update(1)
        loop.close()
        # Fill the buckets
        df_duplicates = df[df['dup_id'] != '[]']
        loop = tqdm(total=df_duplicates.shape[0])
        for row_bug_id, row_dup_id in df_duplicates[['bug_id', 'dup_id']].values:
            bucket_name = int(row_dup_id)
            dup_id = row_bug_id
            while bucket_name not in buckets:
                query = df_duplicates[df_duplicates['bug_id'] == bucket_name]
                bucket_name = int(query['dup_id'])
            buckets[bucket_name].add(dup_id)
            loop.update(1)
        loop.close()
        self.buckets = buckets

    def create_queries(self, path_test):
        print("Creating the queries...")
        test = []
        with open(path_test, 'r') as file_test:
            for row in tqdm(file_test):
                duplicates = np.array(row.split(' '), int)
                # Create the test queries
                query = duplicates[0]
                duplicates = np.delete(duplicates, 0)
                while duplicates.shape[0] > 0:
                    dup = duplicates[0]
                    duplicates = np.delete(duplicates, 0)
                    test.append([query, dup])
        self.test = test

    def read_model(self, name, MAX_SEQUENCE_INFO, MAX_SEQUENCE_LENGTH_T, MAX_SEQUENCE_LENGTH_D):
        
        # name = 'baseline_10000epoch_10steps_512batch(eclipse)'
        similarity_model = Baseline.load_model('', name, {'l2_normalize' : Baseline.l2_normalize})

        bug_t = Input(shape = (MAX_SEQUENCE_LENGTH_T, ), name = 'title')
        bug_d = Input(shape = (MAX_SEQUENCE_LENGTH_D, ), name = 'desc')
        bug_i = Input(shape = (MAX_SEQUENCE_INFO, ), name = 'info')
        # Encoder
        title_encoder = similarity_model.get_layer('FeatureLstmGenerationModel')
        desc_encoder = similarity_model.get_layer('FeatureCNNGenerationModel')
        info_encoder = similarity_model.get_layer('FeatureMlpGenerationModel')
        # Bug feature
        bug_encoded_t = title_encoder(bug_t)
        bug_encoded_d = desc_encoder(bug_d)
        bug_encoded_i = info_encoder(bug_i)

        model = similarity_model.get_layer('merge_features_in')
        output = model([bug_encoded_i, bug_encoded_t, bug_encoded_d])

        model = Model(inputs=[bug_i, bug_t, bug_d], outputs=[output])
        model.compile(optimizer='adam', loss='categorical_crossentropy', metrics = ['accuracy'])
        
        self.model = model

    def read_train(self, path_data):
        self.train = []
        with open(path_data, 'r') as file_train:
            for row in file_train:
                dup_a_id, dup_b_id = np.array(row.split(' '), int)
                self.train.append([dup_a_id, dup_b_id])

    def infer_vector_train(self, bugs, vectorized):
        bug_set = self.baseline.get_bug_set()
        bug_unique = set()
        for row in tqdm(bugs):
            dup_a_id, dup_b_id = row
            bug_unique.add(dup_a_id)
            bug_unique.add(dup_b_id)
        for bug_id in tqdm(list(bug_unique)):
            bug = bug_set[bug_id]
            bug_vector = self.model.predict([[self.get_info(bug)], [bug['title_word']], [bug['description_word']]])[0]
            vectorized.append(bug_vector)
    def infer_vector_test(self, bugs, vectorized):
        bug_set = self.baseline.get_bug_set()
        for row in tqdm(bugs):
            for bug_id in row:
                dup_a_id, dup_b_id = row
                bug = bug_set[bug_id]
                bug_vector = self.model.predict([[self.get_info(bug)], [bug['title_word']], [bug['description_word']]])[0]
                vectorized.append({ 'vector' : bug_vector, 
                                'dup_a' : dup_a_id if bug_id == dup_a_id else dup_b_id,
                                'dup_b' : dup_a_id if bug_id == dup_b_id else dup_b_id })

    def get_info(self, bug):
        info = np.concatenate((
            self.baseline.to_one_hot(bug['bug_severity'], self.baseline.info_dict['bug_severity']),
            self.baseline.to_one_hot(bug['bug_status'], self.baseline.info_dict['bug_status']),
            self.baseline.to_one_hot(bug['component'], self.baseline.info_dict['component']),
            self.baseline.to_one_hot(bug['priority'], self.baseline.info_dict['priority']),
            self.baseline.to_one_hot(bug['product'], self.baseline.info_dict['product']),
            self.baseline.to_one_hot(bug['version'], self.baseline.info_dict['version']))
        )
        return info

    def create_bug_clusters(self, bug_set_cluster, bugs):
        index = 0
        for row in tqdm(bugs):
            dup_a_id, dup_b_id = row
            # if dup_a_id not in bug_set or dup_b_id not in bug_set: continue
            bug_set_cluster[indices[index][:1][0]] = dup_a_id
            bug_set_cluster[indices[index+1][:1][0]] = dup_b_id
            index += 2

    def run(self, path, dataset, path_buckets, path_train, path_test):

        MAX_SEQUENCE_LENGTH_T = 100 # Title
        MAX_SEQUENCE_LENGTH_D = 100 # Description

        # Create the instance from baseline
        self.baseline = Baseline(path, dataset, MAX_SEQUENCE_LENGTH_T, MAX_SEQUENCE_LENGTH_D)

        df = pd.read_csv(path_buckets)

        # Load bug ids
        self.load_bugs(path, path_train)
        # Create the buckets
        self.create_bucket(df)
        # Read and create the test queries duplicate
        self.create_queries(path_test)
        # Read the siamese model
        self.read_model(MAX_SEQUENCE_LENGTH_T, MAX_SEQUENCE_LENGTH_D)
        
        self.train_vectorized, self.test_vectorized = [], []
        self.bug_set_cluster_train, self.bug_set_cluster_test = [], []
        self.read_train(path_train)
        # Infer vector to all train
        self.create_bug_clusters(self.bug_set_cluster_train, self.train)
        self.infer_vector(self.train, self.train_vectorized)
        # Infer vector to all test
        self.create_bug_clusters(self.bug_set_cluster_test, self.test)
        self.infer_vector(self.test, self.test_vectorized)
        # Indexing all train in KNN method
        X = np.array(self.train_vectorized)
        nbrs = NearestNeighbors(n_neighbors=20, algorithm='ball_tree').fit(X)
        # Next we find k nearest neighbor for each point in object X.
        distances, indices = nbrs.kneighbors(X)
        # Recommend neighborhood instances from test sample
        X_test = self.test_vectorized
        distances_test, indices_test = nbrs.kneighbors(X_test)
        # Generating the rank result

if __name__ == '__main__':
    retrieval = Retrieval()
    retrieval.run(
        'data/processed/eclipse', 
        'eclipse.csv',
        'data/normalized/eclipse/eclipse.csv', 
        'data/processed/eclipse/train.txt', 
        'data/processed/eclipse/test.txt')
    print("Retrieval")
