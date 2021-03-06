import pandas as pd
from sklearn import preprocessing
from ast import literal_eval
from sklearn.model_selection import train_test_split
import torch
from transformers import AdamW
from transformers import get_linear_schedule_with_warmup
import numpy as np

import config
import dataset
import engine
import joblib
import argparse
from model import NERModel

def preprocess_data(data_path):
    df = pd.read_csv(data_path)
    df['sentence'] = df['sentence'].apply(literal_eval)
    df['labels'] = df['labels'].apply(literal_eval)
    enc_tags = preprocessing.LabelEncoder()
    
    all_labels = []
    for e in df['labels']:
        all_labels.extend(e)

    enc_tags.fit(all_labels)
    df['labels'] = df['labels'].apply(enc_tags.transform)
    sentences = df['sentence'].values
    tags = df['labels'].values

    return sentences, tags, enc_tags

if __name__ == "__main__":

    my_parser = argparse.ArgumentParser()
    my_parser.version = '1.0'
    my_parser.add_argument('-f','--folderpath', action='store',help='secondary path for saving metadata and model')
    args = my_parser.parse_args()
    SECONDARY_PATH = args.folderpath
    if(SECONDARY_PATH is not None and SECONDARY_PATH[-1] != '/'):
        SECONDARY_PATH += '/'

    sentences = []
    tags = []
    for dataset_name in config.DATASET_LIST:
        TRAINFILE = config.DATASET_PATH + dataset_name + "/" + config.TRAINING_FILE
        sentences_dataset, tags_dataset, enc_tags = preprocess_data(TRAINFILE)
        sentences.extend(sentences_dataset)
        tags.extend(tags_dataset)
    
    sentences = np.array(sentences)
    tags = np.array(tags)

    meta_data = {
        'enc_tags' : enc_tags
    }
    joblib.dump(meta_data, 'meta.bin')
    if(SECONDARY_PATH is not None):
        joblib.dump(meta_data, SECONDARY_PATH+'meta.bin')
        print('saved metadata to : ',SECONDARY_PATH+'meta.bin')

    num_tags = len(list(enc_tags.classes_))

    (
        train_sentences,
        val_sentences,
        train_tags,
        val_tags
    ) = train_test_split(sentences, tags, test_size=0.1,random_state=17)

    train_dataset = dataset.NERdataset(train_sentences, train_tags)
    val_dataset = dataset.NERdataset(val_sentences, val_tags)

    train_dataloader = torch.utils.data.DataLoader(
        dataset = train_dataset,
        batch_size = config.TRAIN_BATCH_SIZE
    )

    val_dataloader = torch.utils.data.DataLoader(
        dataset = val_dataset,
        batch_size = config.VALID_BATCH_SIZE
    )

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = NERModel(num_tags)
    model.to(device)

    param_optimizer = list(model.named_parameters())
    no_decay = ["bias", "LayerNorm.bias", "LayerNorm.weight"]
    optimizer_parameters = [
        {
            "params": [
                p for n, p in param_optimizer if not any(nd in n for nd in no_decay)
            ],
            "weight_decay": 0.001,
        },
        {
            "params": [
                p for n, p in param_optimizer if any(nd in n for nd in no_decay)
            ],
            "weight_decay": 0.0,
        },
    ]

    num_train_steps = int(len(train_sentences) / config.TRAIN_BATCH_SIZE * config.EPOCHS)
    optimizer = AdamW(optimizer_parameters, lr=3e-5)
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=0, num_training_steps=num_train_steps
    )

    best_loss = np.inf
    for epoch in range(config.EPOCHS):
        train_loss = engine.train_fn(train_dataloader, model, optimizer, scheduler, device)
        test_loss = engine.eval_fn(val_dataloader, model, device)
        print(f"Train Loss = {train_loss} Valid Loss = {test_loss}")
        if test_loss < best_loss:
            torch.save(model.state_dict(), config.MODEL_PATH)
            if SECONDARY_PATH is not None:
                torch.save(model.state_dict(), SECONDARY_PATH+'model.bin')
                print('saved model to : ',SECONDARY_PATH+'model.bin')
            best_loss = test_loss