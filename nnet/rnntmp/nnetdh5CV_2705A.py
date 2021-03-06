# https://www.kaggle.com/darraghdog/mem-check-1002-ftrlrnnverified
# Models Packages
from sklearn import metrics
from sklearn.metrics import mean_squared_error
import time, gc
import pandas as pd
import numpy as np
from sklearn import preprocessing
from nltk.corpus import stopwords
from sklearn.pipeline import FeatureUnion
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from scipy.sparse import hstack, csr_matrix
from sklearn.model_selection import train_test_split
import plotly.offline as plt
import plotly.graph_objs as go
from numba import jit
import nltk, re
from nltk.corpus import stopwords
from nltk.tokenize import ToktokTokenizer
import pymorphy2
import multiprocessing as mp
from collections import Counter
from keras.preprocessing.sequence import pad_sequences
import random
from keras.layers import *
from keras.models import Model
from keras.callbacks import ModelCheckpoint, Callback, EarlyStopping#, TensorBoard
from keras import backend as K
from keras import optimizers
from keras.layers import GlobalMaxPooling1D
from keras import initializers
from keras.utils import plot_model
from keras.regularizers import l2
from keras.constraints import non_neg, Constraint
from keras.utils.data_utils import Sequence
from sklearn import preprocessing
import math

path = "../"
#path = '../input/'
path = "/home/darragh/avito/data/"
#path = '/Users/dhanley2/Documents/avito/data/'
# path = '/home/ubuntu/avito/data/'

start_time = time.time()

validation = False
full       = True
CV   = True

print('[{}] Load Train/Test'.format(time.time() - start_time))
traindf = pd.read_csv(path + 'train.csv.zip', index_col = "item_id", parse_dates = ["activation_date"], compression = 'zip')
traindex = traindf.index
testdf = pd.read_csv(path + 'test.csv.zip', index_col = "item_id", parse_dates = ["activation_date"])
testdex = testdf.index
y = traindf.deal_probability.copy()

traindf.drop("deal_probability",axis=1, inplace=True)
print('Train shape: {} Rows, {} Columns'.format(*traindf.shape))
print('Test shape: {} Rows, {} Columns'.format(*testdf.shape))
traindf['activation_date'].value_counts()
traindf.head()

print('[{}] Create Validation Index'.format(time.time() - start_time))
if full:
    trnidx = (traindf.activation_date<=pd.to_datetime('2017-03-28')).values
    validx = (traindf.activation_date>=pd.to_datetime('2017-03-29')).values
else:
    trnidx = (traindf.activation_date<=pd.to_datetime('2017-03-26')).values
    validx = (traindf.activation_date>=pd.to_datetime('2017-03-27')).values

print('[{}] Load Densenet image features'.format(time.time() - start_time))
dnimgtrn = np.load(path+'../imgfeatures/densenet_pool_array_train.npy')
dnimgtrn = dnimgtrn
scaler = preprocessing.StandardScaler()
dnimgtrn = scaler.fit_transform(dnimgtrn)
gc.collect()
dnimgtst = np.load(path+'../imgfeatures/densenet_pool_array_test.npy')
dnimgtst = scaler.transform(dnimgtst)
gc.collect()


print('[{}] Combine Train and Test'.format(time.time() - start_time))
df = pd.concat([traindf,testdf],axis=0)
df['idx'] = range(df.shape[0])
del traindf,testdf
gc.collect()
print('\nAll Data shape: {} Rows, {} Columns'.format(*df.shape))

print('[{}] Create folds'.format(time.time() - start_time))
foldls = [["2017-03-15", "2017-03-16", "2017-03-17"], \
       ["2017-03-18", "2017-03-19", "2017-03-20"], \
       ["2017-03-21", "2017-03-22", "2017-03-23"], \
       ["2017-03-24", "2017-03-25", "2017-03-26"], \
        ["2017-03-27", "2017-03-28", "2017-03-29", \
            "2017-03-30", "2017-03-31", "2017-04-01", \
            "2017-04-02", "2017-04-03","2017-04-07"]]
foldls = [[pd.to_datetime(d) for d in f] for f in foldls]
df['fold'] = -1
for t, fold in enumerate(foldls):
    df['fold'][df.activation_date.isin(fold)] = t
df['fold'].value_counts()
df.head()

df.isnull().sum()

print('[{}] Missing values'.format(time.time() - start_time))
for col in ['param_1', 'param_2', 'param_3', 'description', 'price', 'image']:
    df["bin_no_" + col] = (df[col] != df[col]).astype(np.int32)
cols = [c for c in df.columns if 'bin_no_' in c]
df[cols].head()

print('[{}] Feature Engineering Price'.format(time.time() - start_time))
col = "price"
bins_ = 100
for col in ['price', 'item_seq_number']:
    df['emb_' + col] = pd.qcut(df[col], q = bins_, labels = False, duplicates = 'drop')
    df['emb_' + col].fillna(-1,inplace=True)
    df['emb_' + col].value_counts()
    df["cont_log_%s"%(col)] = np.log(df[col]+0.001)
    df["cont_log_%s"%(col)].fillna(-1,inplace=True)
df["image_top_1"].fillna(-1,inplace=True)



print('[{}] Create Time Variables'.format(time.time() - start_time))
df["emb_weekday"] = df['activation_date'].dt.weekday
#df["cont_week_of_year"] = df['activation_date'].dt.week    <- Too different between train and test
df.drop(["activation_date","image"],axis=1,inplace=True)

print('[{}] Text Features'.format(time.time() - start_time))
df['text_feat'] = df.apply(lambda row: ' '.join([
    str(row['param_1']),
    str(row['param_2']),
    str(row['param_3'])]),axis=1) # Group Param Features
for col in ['title', 'description', 'text_feat']:
    df[col] = df[col].str.lower()
df['description'] = df['title'].fillna('missd') + ' ' + df["parent_category_name"].fillna('') + ' ' \
                    + df["category_name"].fillna('') + ' ' + df['text_feat'].fillna('') + \
                    ' ' + df['description'].fillna('')

print('[{}] Categoricals with some low counts'.format(time.time() - start_time))
def lowCtCat(col, cutoff = 20):
    dft         = pd.DataFrame(df[col].values, columns = [col])
    gp          = dft[col].value_counts().reset_index().rename(columns = {'index':col, col:col+'_ct'})
    var         = dft[[col]].merge(gp, on = col, how = 'left')[col+'_ct']
    idx         = var>cutoff
    var[idx]    = (df[col].values)[idx]
    var[~idx]    = 'locount'
    var.fillna('missing', inplace = True)
    return var.astype(str).values
for col_, cut_ in [("user_id", 5), ("image_top_1", 30), ("item_seq_number", 100)]:
    df[col_] = lowCtCat(col_, cutoff = cut_)
for col_, cut_ in [('param_'+str(i+1), 20) for i in range(3)]:
    df['cat_' + col_] = lowCtCat(col_, cutoff = cut_)


print('[{}] Encode Variables'.format(time.time() - start_time))
embed_me = ["emb_item_seq_number", "user_id","image_top_1", "region", 'city', 'emb_price', \
            "parent_category_name", "category_name", "user_type", "emb_weekday", 'text_feat'] \
            + ['cat_param_'+str(i+1) for i in range(3)]
for col in embed_me:
    print('Label encode %s'%(col))
    lbl = preprocessing.LabelEncoder()
    df[col] = lbl.fit_transform(df[col].astype(str))

print('[{}] Scale Variables'.format(time.time() - start_time))
scl = StandardScaler()
for col in df.columns:
    if 'cont_' in col:
        print('Scale %s'%(col))
        df[col] = scl.fit_transform(df[col].values.reshape(-1, 1)).flatten()

print('[{}] Embedding dimensions'.format(time.time() - start_time))
col_szs = dict((col, df[col].unique().shape[0]) for col in embed_me)
embed_szs = dict((col, int(np.ceil(np.log(col_szs[col])))+1) for col in embed_me)
print(embed_szs)

print('[{}] Clean text and tokenize'.format(time.time() - start_time))
toktok = ToktokTokenizer()
tokSentMap = {}
stopwords_set = set(stopwords.words('russian'))
morpher = pymorphy2.MorphAnalyzer()
def tokSent(sent):
   sent = sent.replace('/', ' ')
   return " ".join(morpher.parse(word)[0].normal_form for word in toktok.tokenize(rgx.sub(' ', sent)) if word not in stopwords_set)

def tokCol(var):
   return [tokSent(s) for s in var.tolist()]
rgx = re.compile('[%s]' % '!"#%&()*,-./:;<=>?@[\\]^_`{|}~\t\n')

from multiprocessing import cpu_count, Pool

partitions = min(cpu_count(), 8) #Define as many partitions as you want
cores=4
def parallelize(data, func):
   data_split = np.array_split(data.values, partitions)
   pool = Pool(cores)
   data = pd.concat([pd.Series(l) for l in pool.map(tokCol, data_split)]).values
   pool.close()
   pool.join()
   return data

for col in ['description', 'title',]:
   print('Tokenise %s'%(col))
   df[col] = parallelize(df[col], tokCol)
print('[{}] Finished tokenizing text...'.format(time.time() - start_time))

@jit
def myTokenizerFitJit(strls, max_words, filt = True):
    list_=[]
    for sent in strls:
        if filt:
            sent = rgx.sub(' ', sent)
        for s in sent.split(' '):
            if s!= '':
                list_.append(s)
    return Counter(list_).most_common(max_words)

def myTokenizerFit(strls, max_words = 25000):
    mc = myTokenizerFitJit(strls, max_words)
    return dict((i, c+1) for (c, (i, ii)) in enumerate(mc))

@jit
def fit_sequence(str_, tkn_, filt = True):
    labels = []
    for sent in str_:
        if filt:
            sent = rgx.sub(' ', sent)
        tk = []
        for i in sent.split(' '):
            if i in tkn_:
                if i != '':
                    tk.append(tkn_[i])
        labels.append(tk)
    return labels

print('[{}] Finished FITTING TEXT DATA...'.format(time.time() - start_time))
tok_raw = myTokenizerFit(df['description'].loc[traindex].values.tolist()+df['title'].loc[traindex].values.tolist(), max_words = 80000)
print('[{}] Finished PROCESSING TEXT DATA...'.format(time.time() - start_time))

df["title"]       = fit_sequence(df.title, tok_raw)
df["description"] = fit_sequence(df.description, tok_raw)
df["title"]       = [l if len(l)>0 else [0] for l in df["title"]]
gc.collect()


MAX_DSC = max(tok_raw.values())+1
MAX_TTL = max(tok_raw.values())+1

bin_cols = [c for c in df.columns if 'bin_no' in c]
cont_cols = [c for c in df.columns if 'cont_' in c]


#TEST DOESNT HAVE ANY 1s
bin_cols=[x for x in bin_cols if x!='bin_no_description']



print('[{}] Finished FEATURE CREATION'.format(time.time() - start_time))



def map_sort(seq1, seq2):
	return sorted(range(len(seq1)), key=lambda x: max(len(seq1[x]),len(seq2[x])))




class Seq_generator(Sequence):
    def __init__(self, dt, dn, bsize, sort_vals, target_out=True):
        self.batch_size = bsize
        self.dt = dt.iloc[sort_vals].reset_index(drop=True)
        self.dn = dn[sort_vals]
        if target_out:
            self.y = self.dt.target.values
        else:
            self.y = None

    def get_keras_data(self, dataset, dndataset):
        X = {
            'title': pad_sequences(dataset.title,
                                  maxlen=max([len(l) for l in dataset.title]))
            ,'description': pad_sequences(dataset.description,
                                  maxlen=max([len(l) for l in dataset.description]))
            }
        for col in embed_szs.keys():
            X[col] = dataset[col].values
        X['bin_vars'] = dataset[bin_cols].values
        X['cont_vars'] = dataset[cont_cols].values
        X['img_layer'] = dndataset
        return X

    def __len__(self):
        return int(np.ceil(self.dt.shape[0]*1./self.batch_size))

    def __getitem__(self, i):
        slc = slice(i*self.batch_size, min((i+1)*self.batch_size, self.dt.shape[0]))
        X = self.get_keras_data(self.dt.iloc[slc], self.dn[slc])
        if self.y is not None:
            return (X, self.y[slc])
        return X

def get_model(emb_size = 32, dr = 0.1, l2_val = 0.0001):

    def root_mean_squared_error(y_true, y_pred):
        return K.sqrt(K.mean(K.square(y_pred - y_true)))


    def mean_error(y_true, y_pred):
        return K.mean(y_true-y_pred)

    class FreezePadding(Constraint):
        """Freezes the last weight to be near 0."""
        def __call__(self, w):
            other_weights = K.cast(K.ones(K.shape(w))[1:], K.floatx())
            last_weight = K.cast(K.equal(K.reshape(w[0, :], (1, K.shape(w)[1])), 0.), K.floatx())
            appended = K.concatenate([other_weights, last_weight], axis=0)
            w *= appended
            return w

    ##Inputs
    title = Input(shape=[None], name="title")
    description = Input(shape=[None], name="description")
    img_layer = Input(shape=[dnimgtrn.shape[1]], name="img_layer")
    

    # Categorical embeddings
    emb_inputs = dict((col, Input(shape=[1], name = col))  for col in embed_szs.keys())
    emb_model  = dict((col, Embedding(col_szs[col]+1, emb_n, embeddings_regularizer=l2(l2_val))(emb_inputs[col])) for (col, emb_n) in embed_szs.items())
    fe = concatenate([(emb_) for emb_ in emb_model.values()])
    #fe = SpatialDropout1D(dr)(fe)
    
    dense_l = Dropout(0.1) (Dense(256,activation='relu', kernel_regularizer=l2(l2_val)) (img_layer))
    dense_l = Dropout(0.1) (Dense(32,activation='relu', kernel_regularizer=l2(l2_val)) (dense_l))

    # Binary Inputs
    bin_vars = Input(shape= [len(bin_cols)], name = 'bin_vars')
    ## Continuous Inputs
    cont_vars = Input(shape= [len(cont_cols)], name = 'cont_vars')

    #Embeddings layers
    #emb_size = 64
    embs_text = Embedding(MAX_DSC, emb_size, embeddings_regularizer=l2(l2_val), embeddings_constraint=FreezePadding())
    emb_dsc = embs_text(description)
    emb_ttl = embs_text(title)

    # GRU Layer
    rnn_dsc = (CuDNNGRU(emb_size))(emb_dsc)
    rnn_ttl = (CuDNNGRU(emb_size)) (emb_ttl)
    #rnn_dsc = (GRU(emb_size))(emb_dsc)
    #rnn_ttl = (GRU(emb_size)) (emb_ttl)

    #main layer
    main_l = concatenate([
        rnn_dsc
        , rnn_ttl
        , Flatten()(fe)
        , bin_vars
        , cont_vars
        , dense_l
    ])  
    #main_l = BatchNormalization()(main_l)
    main_l = Dense(32, kernel_regularizer=l2(l2_val)) (main_l)
    main_l = PReLU()(main_l)
    #main_l = BatchNormalization()(main_l)
    main_l = Dropout(dr)(main_l)
    main_l = Dense(16, kernel_regularizer=l2(l2_val)) (main_l)
    main_l = PReLU()(main_l)
    #main_l = BatchNormalization()(main_l)
    main_l = Dropout(dr/2)(main_l)

    #output
    output = Dense(1,activation="linear", kernel_regularizer=l2(l2_val)) (main_l)

    #model
    model = Model([title, description] + [inp for inp in emb_inputs.values()] + [bin_vars] + [cont_vars] + [img_layer], output)
    #optimizer = optimizers.Adam(clipnorm=10)
    optimizer = optimizers.Adam(clipvalue=0.5)
    model.compile(loss=root_mean_squared_error,
                  optimizer=optimizer, metrics=['mae'])

    return model

def to_logit(ls):
    ls=np.array(ls)
    ls=np.clip(ls,.0001,.9999)
    return np.log(ls/(1-ls))

def to_proba(ls):
    return 1/(1+np.exp(-ls))


# Placeholder for predictions
df['fold'].value_counts()
y_pred_trn = pd.Series(-np.zeros(df.loc[traindex,:].shape[0]), index = traindex)
y_pred_tst = pd.Series(-np.zeros(df.loc[testdex ,:].shape[0]), index = testdex)
for f in range(6):
    print('Fold %s'%(f) + ' [{}] Modeling Stage'.format(time.time() - start_time))
    trnidx = (df['fold'].loc[traindex] != f).values
    dtrain = df.loc[traindex,:][trnidx].reset_index()
    dtrain['target'] = y[trnidx].values
    dnfimgtrn = dnimgtrn[trnidx]
    # 5 is the test fold
    if f == 5:
        dtest  = df.loc[testdex,:].reset_index()
        dnfimgtst = dnimgtst
    else:
        dtest  = df.loc[traindex,:][~trnidx].reset_index()
        dnfimgtst = dnimgtrn[~trnidx]
        dtest['target'] = y[~trnidx].values
    
    train_sorted_ix = np.array(map_sort(dtrain["title"].tolist(), dtrain["description"].tolist()))
    tst_sorted_ix = np.array(map_sort(dtest ["title"].tolist(), dtest ["description"].tolist()))
    
    y_pred_epochs = []
    epochs = 26
    batchSize = 512
    steps = (dtrain.shape[0]/batchSize+1)*epochs
    lr_init, lr_fin = 0.0014, 0.00001
    lr_decay  = (lr_init - lr_fin)/steps


    bags      = 3
    y_pred_ls = []
    y_sub_ls  = []
    for b in range(bags):
        model = get_model(128, .1,.00001)
        K.set_value(model.optimizer.lr, lr_init)
        K.set_value(model.optimizer.decay, lr_decay)
        #model.summary()
        for i in range(epochs):
            batchSize = min(512*(2**i),512)
            batchSizeTst = 256
            history = model.fit_generator(
                                Seq_generator(dtrain, dnfimgtrn, batchSize, train_sorted_ix)
                                , epochs=i+1
                                , max_queue_size=15
                                , verbose=1
                                , initial_epoch=i
                                , use_multiprocessing=True
                                , workers=3
                                )
            if i>6:
                y_sub_ls.append(model.predict_generator(
                                Seq_generator(dtest, dnfimgtst, batchSizeTst, tst_sorted_ix, target_out=False)
                                , max_queue_size=10
                                , verbose=2)[tst_sorted_ix.argsort()])
                if f == 5:
                    if len(y_pred_ls)>1:
                        y_pred_tst[:] = sum(y_sub_ls)/len(y_sub_ls)
                else:
                    print('RMSE:', np.sqrt(metrics.mean_squared_error(dtest['target'], y_sub_ls[-1].flatten())))
                    if len(y_sub_ls)>1:
                        y_pred = sum(y_sub_ls)/len(y_sub_ls)
                        print('RMSE bags:', np.sqrt(metrics.mean_squared_error(dtest['target'], y_pred.flatten()))) 
                        y_pred_trn[~trnidx] = y_pred
            gc.collect()
    del dtrain, dtest, dnfimgtrn, dnfimgtst
    gc.collect()

rnnsub = pd.concat([y_pred_trn, y_pred_tst]).reset_index()
rnnsub.rename(columns = {0 : 'deal_probability'}, inplace=True)
rnnsub['deal_probability'].clip(0.0, 1.0, inplace=True)
rnnsub.set_index('item_id', inplace = True)
print('RMSE for all :', np.sqrt(metrics.mean_squared_error(y, rnnsub.loc[traindex])))
# RMSE for all : 0.2168
rnnsub.to_csv("../sub/rnndhCV_2705A.csv.gz",index=True,header=True, compression = 'gzip')
