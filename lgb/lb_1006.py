# https://www.kaggle.com/tunguz/bow-meta-text-and-dense-features-lgbm-clone?scriptVersionId=3540839

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
from scipy.sparse import hstack, csr_matrix
from sklearn.model_selection import train_test_split
import lightgbm as lgb
import matplotlib.pyplot as plt
import pymorphy2
import nltk, re
from nltk.tokenize import ToktokTokenizer
from multiprocessing import cpu_count, Pool


#path = '../input/'
path = "/home/darragh/avito/data/"
#path = '/Users/dhanley2/Documents/avito/data/'
path = '/home/ubuntu/avito/data/'
start_time = time.time()
full = False

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

(traindf['image_top_1'] == traindf['image_top_1']).value_counts()
(testdf['image_top_1'] == testdf['image_top_1']).value_counts()



print('[{}] Create Validation Index'.format(time.time() - start_time))
if full:
    trnidx = (traindf.activation_date<=pd.to_datetime('2017-03-28')).values
    validx = (traindf.activation_date>=pd.to_datetime('2017-03-29')).values
else:
    trnidx = (traindf.activation_date<=pd.to_datetime('2017-03-26')).values
    validx = (traindf.activation_date>=pd.to_datetime('2017-03-27')).values

print('[{}] Combine Train and Test'.format(time.time() - start_time))
df = pd.concat([traindf,testdf],axis=0)
del traindf,testdf
gc.collect()
df['idx'] = range(df.shape[0])
print('\nAll Data shape: {} Rows, {} Columns'.format(*df.shape))

#print('[{}] Count NA row wise'.format(time.time() - start_time))
#df['NA_count_rows'] = df.isnull().sum(axis=1)

print('[{}] Load meta image engineered features'.format(time.time() - start_time))
featimgmeta = pd.concat([pd.read_csv(path + '../features/img_features_%s.csv.gz'%(i)) for i in range(6)])
featimgmeta.rename(columns = {'name':'image'}, inplace = True)
featimgmeta['image'] = featimgmeta['image'].str.replace('.jpg', '')
df = df.reset_index('item_id').merge(featimgmeta, on = ['image'], how = 'left').set_index('item_id')
for col in featimgmeta.columns.values[1:]:
    df[col].fillna(-1, inplace = True)
    df[col].astype(np.float32, inplace = True)
    
print('[{}] Load translated image engineered features'.format(time.time() - start_time))
feattrlten = pd.concat([pd.read_pickle(path + '../features/translate_en.pkl'),
                       pd.read_pickle(path + '../features/translate_tst_en.pkl')])
feattrlten['translation'] = feattrlten['title_translated'] + ' ' + feattrlten['param_1_translated'] + ' ' \
            + feattrlten['param_2_translated'] + ' ' + feattrlten['param_3_translated'] + ' '  \
            + feattrlten['category_name_translated'] + ' ' + feattrlten['parent_category_name_translated']
feattrlten = feattrlten[['translation']]
df = pd.merge(df, feattrlten, left_index=True, right_index=True, how='left')
del feattrlten
df['translation'].fillna('', inplace = True)
gc.collect()
 
print('[{}] Load other engineered features'.format(time.time() - start_time))
featlatlon = pd.read_csv(path + '../features/avito_region_city_features.csv') # https://www.kaggle.com/frankherfert/region-and-city-details-with-lat-lon-and-clusters
featlatlon.drop(['city_region', 'city_region_id', 'region_id'], 1, inplace = True)
featpop    = pd.read_csv(path + '../features/city_population_wiki_v3.csv') # https://www.kaggle.com/stecasasso/russian-city-population-from-wikipedia/comments
featusrttl = pd.read_csv(path + '../features/user_agg.csv.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featusrcat = pd.read_csv(path + '../features/usercat_agg.csv.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featusrprd = pd.read_csv(path + '../features/user_activ_period_stats.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featrdgtxt = pd.read_csv(path + '../features/ridgeText5CV.csv.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
#featrdgtxts = pd.read_csv(path + '../features/ridgeTextStr5CV.csv.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featrdgimg = pd.read_csv(path + '../features/ridgeImg5CV.csv.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
#featrdgprc = pd.read_csv(path + '../features/price_category_ratios.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featrdgprc = pd.read_csv(path + '../features/price_seq_category_ratios.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featrdgprc.fillna(-1, inplace = True)
featrdgrnk = pd.read_csv(path + '../features/price_rank_ratios0906.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featrdgrnk.isnull().sum()
featimgprc = pd.read_csv(path + '../features/price_imagetop1_ratios.gz', compression = 'gzip') # created with features/make/priceImgRatios2705.R
featenc = pd.read_csv(path + '../features/alldf_bayes_mean.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featnumf = pd.read_csv(path + '../features/numericFeats.gz', compression = 'gzip') 
featnumf.fillna(0, inplace = True)
featct  = pd.read_csv(path + '../features/alldf_count.gz', compression = 'gzip') # created with features/make/user_actagg_1705.py
featusrttl.rename(columns={'title': 'all_titles'}, inplace = True)
df = df.reset_index().merge(featpop, on = 'city', how = 'left')
df = df.merge(featlatlon, on = ['city', 'region'], how = 'left')
df['population'].fillna(-1, inplace = True)
df = df.set_index('item_id')
keep = ['user_id', 'all_titles', 'user_avg_price', 'user_ad_ct']
df = df.reset_index().merge(featusrttl[keep], on = 'user_id').set_index('item_id')
keep = ['user_id', 'parent_category_name', 'usercat_avg_price', 'usercat_ad_ct']
gc.collect()
df = df.reset_index().merge(featusrcat[keep], on = ['user_id', 'parent_category_name']).set_index('item_id')
keep = ['user_id', 'user_activ_sum', 'user_activ_mean', 'user_activ_var']
gc.collect()
df = df.reset_index().merge(featusrprd[keep], on = ['user_id'], how = 'left').set_index('item_id')
print('\nAll Data shape: {} Rows, {} Columns'.format(*df.shape))  

print('[{}] Resort data correctly'.format(time.time() - start_time))
df.sort_values('idx', inplace = True)
df.drop(['idx'], axis=1,inplace=True)
df.reset_index(inplace = True)
df.head()
df = pd.concat([df.reset_index(),featenc, featct, featrdgtxt, featrdgprc, featimgprc, featrdgrnk, featnumf],axis=1)
#df['ridge_txt'] = featrdgtxt['ridge_preds'].values
#df = pd.concat([df.reset_index(),featenc, featct, ],axis=1)
df['ridge_img'] = featrdgimg['ridge_img_preds'].values
df = df.set_index('item_id')
df.drop(['index'], axis=1,inplace=True)
df.columns
del featusrttl, featusrcat, featusrprd, featenc, featrdgprc, featimgprc, featrdgrnk
# del featusrttl, featusrcat, featusrprd, featenc, featrdgtxts
gc.collect()

print('[{}] Feature Engineering'.format(time.time() - start_time))
for col in df.columns:
    if 'price' in col:
        print(f'Fill {col}')
        df[col].fillna(-999,inplace=True)

for col in df.columns:
    if 'user_activ' in col:
        print(f'fill {col}')
        df[col].fillna(-9,inplace=True)
df["image_top_1"].fillna(-999,inplace=True)

del featct, featlatlon, featimgmeta, featpop, featrdgimg, featrdgtxt
gc.collect()

print('[{}] Manage Memory'.format(time.time() - start_time))
for col in df.columns:
    if np.float64 == df[col].dtype:
        df[col] = df[col].astype(np.float32)
    if np.int64 == df[col].dtype:
        df[col] = df[col].astype(np.int32)
    gc.collect()
df.dtypes


print('[{}] Text Features'.format(time.time() - start_time))
df['text_feat'] = df.apply(lambda row: ' '.join([
    str(row['param_1']), 
    str(row['param_2']), 
    str(row['param_3'])]),axis=1) # Group Param Features
df.drop(["param_1","param_2","param_3"],axis=1,inplace=True)

print('[{}] Text Features'.format(time.time() - start_time))
df['description'].fillna('unknowndescription', inplace=True)
df['title'].fillna('unknowntitle', inplace=True)
df['text']      = (df['description'].fillna('') + ' ' + df['title'] + ' ' + 
  df['parent_category_name'].fillna('').astype(str) + ' ' + df['category_name'].fillna('').astype(str) )

print('[{}] Create Time Variables'.format(time.time() - start_time))
df["Weekday"] = df['activation_date'].dt.weekday
df.drop(["activation_date","image"],axis=1,inplace=True)

print('[{}] Make Item Seq number as contiuous also'.format(time.time() - start_time))
df["item_seq_number_cont"] = df["item_seq_number"]
df['city'] = df['region'].fillna('').astype(str) + '_' + df['city'].fillna('').astype(str)
df.columns
print('[{}] Encode Variables'.format(time.time() - start_time))
df.drop(['user_id'], 1, inplace = True)
categorical = ["region","parent_category_name","user_type", 'city', 'category_name', "item_seq_number", 'image_top_1']
print("Encoding :",categorical)
# Encoder:
lbl = preprocessing.LabelEncoder()
for col in categorical:
    df[col] = lbl.fit_transform(df[col].astype(str))
  
print('[{}] Meta Text Features'.format(time.time() - start_time))
textfeats = ["description","text_feat", "title"]
for cols in textfeats:
    df[cols] = df[cols].astype(str) 
    df[cols] = df[cols].astype(str).fillna('nicapotato') # FILL NA
    df[cols] = df[cols].str.lower() # Lowercase all text, so that capitalized words dont get treated differently
    df[cols + '_num_chars'] = df[cols].apply(len) # Count number of Characters
    df[cols + '_num_words'] = df[cols].apply(lambda comment: len(comment.split())) # Count number of Words
    df[cols + '_num_unique_words'] = df[cols].apply(lambda comment: len(set(w for w in comment.split())))
    df[cols + '_words_vs_unique'] = df[cols+'_num_unique_words'] / df[cols+'_num_words'] * 100 # Count Unique Words
    gc.collect()
df.info()
for cols in ['translation']:
    df[cols] = df[cols].astype(str) 
    df[cols] = df[cols].astype(str).fillna('nicapotato') # FILL NA
    df[cols] = df[cols].str.lower() # Lowercase all text, so that capitalized words dont get treated differently

    
print('[{}] Manage Memory'.format(time.time() - start_time))
for col in df.columns:
    if np.float64 == df[col].dtype:
        df[col] = df[col].astype(np.float32)
    if np.int64 == df[col].dtype:
        df[col] = df[col].astype(np.int32)
    gc.collect()
df.info()


print('[{}] Clean text and tokenize'.format(time.time() - start_time))
toktok = ToktokTokenizer()
tokSentMap = {}
morpher = pymorphy2.MorphAnalyzer()
def tokSent(sent):
    sent = sent.replace('/', ' ')
    return " ".join(morpher.parse(word)[0].normal_form for word in toktok.tokenize(rgx.sub(' ', sent)))
def tokCol(var):
    return [tokSent(s) for s in var.tolist()]
rgx = re.compile('[%s]' % '!"#%&()*,-./:;<=>?@[\\]^_`{|}~\t\n')   

partitions = 4 
def parallelize(data, func):
    data_split = np.array_split(data.values, partitions)
    pool = Pool(partitions)
    data = pd.concat([pd.Series(l) for l in pool.map(tokCol, data_split)]).values
    pool.close()
    pool.join()
    return data

load_text = True
text_cols = ['description', 'text', 'text_feat', 'title', 'translation']
if load_text:
    dftxt = pd.read_csv(path + '../features/text_features_morphed.csv.gz', compression = 'gzip')
    for col in text_cols:
        print(col + ' load tokenised [{}]'.format(time.time() - start_time))
        df[col] = dftxt[col].values
        df.fillna(' ', inplace = True)
    del dftxt
else:
    for col in text_cols:
        print(col + ' tokenise [{}]'.format(time.time() - start_time))
        df[col] = parallelize(df[col], tokCol)
    df[text_cols].to_csv(path + '../features/text_features_morphed.csv.gz', compression = 'gzip')
gc.collect()

print('[{}] Finished tokenizing text...'.format(time.time() - start_time))
df.head()
print('[{}] [TF-IDF] Term Frequency Inverse Document Frequency Stage'.format(time.time() - start_time))
russian_stop = set(stopwords.words('russian'))
tfidf_para = {
    "stop_words": russian_stop,
    "token_pattern": r'\w{1,}',
    "sublinear_tf": True,
    "dtype": np.float32,
    "smooth_idf":False
}
countv_para = {
    "stop_words": russian_stop,
    "analyzer": 'word',
    "token_pattern": r'\w{1,}',
    "lowercase": True,
    "min_df": 5 #False
}
def get_col(col_name): return lambda x: x[col_name]
vectorizer = FeatureUnion([
        ('text',TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=50000,
            **tfidf_para,
            preprocessor=get_col('text'))),
        ('text_feat',CountVectorizer(
            **countv_para,
            preprocessor=get_col('text_feat'))),
        ('title',CountVectorizer(
            **countv_para,
            preprocessor=get_col('title'))),
        ('translation',TfidfVectorizer(
            #ngram_range=(1, 2),
            max_features=40000,
            **tfidf_para,
            preprocessor=get_col('translation'))),
    ])
    
start_vect=time.time()
vectorizer.fit(df.loc[traindex,:].to_dict('records'))
ready_df = vectorizer.transform(df.to_dict('records'))
tfvocab = vectorizer.get_feature_names()
tfvocab[:50]
print('[{}] Vectorisation completed'.format(time.time() - start_time))
# Drop Text Cols
df.drop(textfeats+['text', 'all_titles', 'translation'], axis=1,inplace=True)
gc.collect()

print('[{}] Drop all the categorical'.format(time.time() - start_time))
df.drop(categorical, axis=1,inplace=True)

ready_df.shape

print('[{}] Modeling Stage'.format(time.time() - start_time))
# Combine Dense Features with Sparse Text Bag of Words Features
X_train = hstack([csr_matrix(df.loc[traindex,:][trnidx].values),ready_df[0:traindex.shape[0]][trnidx]])
X_valid = hstack([csr_matrix(df.loc[traindex,:][validx].values),ready_df[0:traindex.shape[0]][validx]])
y_train = y[trnidx]
y_valid = y[validx]
testing = hstack([csr_matrix(df.loc[testdex,:].values),ready_df[traindex.shape[0]:]])
tfvocab = df.columns.tolist() + tfvocab
for shape in [X_train, X_valid,testing]:
    print("{} Rows and {} Cols".format(*shape.shape))
print("Feature Names Length: ",len(tfvocab))
del df
gc.collect();


# Training and Validation Set
lgbm_params = {
    'task': 'train',
    'boosting_type': 'gbdt',
    'objective' : 'regression',
    'metric' : 'rmse',
    'num_leaves' : 250,
    'learning_rate' : 0.02,
    'feature_fraction' : 0.5,
    'verbosity' : 0
}

# LGBM Dataset Formatting 
lgtrain = lgb.Dataset(X_train, y_train,
                feature_name=tfvocab)
lgvalid = lgb.Dataset(X_valid, y_valid,
                feature_name=tfvocab)

# Go Go Go
modelstart = time.time()
if full:
    lgb_clf = lgb.train(
        lgbm_params,
        lgtrain,
        num_boost_round=1676, #14686,
        valid_sets=[lgtrain, lgvalid],
        valid_names=['train','valid'],
        #early_stopping_rounds=500,
        verbose_eval=20)    
else:
    lgb_clf = lgb.train(
        lgbm_params,
        lgtrain,
        num_boost_round=15000,
        valid_sets=[lgtrain, lgvalid],
        valid_names=['train','valid'],
        early_stopping_rounds=60,
        verbose_eval=20)

# Feature Importance Plot
f, ax = plt.subplots(figsize=[7,10])
lgb.plot_importance(lgb_clf, max_num_features=50, ax=ax)
plt.title("Light GBM Feature Importance")
plt.savefig(path + '../plots/feature_import_1006.png')

print("Model Evaluation Stage")
print('RMSE:', np.sqrt(metrics.mean_squared_error(y_valid, lgb_clf.predict(X_valid))))
lgpred = lgb_clf.predict(testing)
lgsub = pd.DataFrame(lgpred,columns=["deal_probability"],index=testdex)
lgsub['deal_probability'].clip(0.0, 1.0, inplace=True) # Between 0 and 1
#lgsub.to_csv(path + "../sub/lgsub_0206A.csv.gz",index=True,header=True, compression = 'gzip')
print("Model Runtime: %0.2f Minutes"%((time.time() - modelstart)/60))



'''

[20]    train's rmse: 0.240974  valid's rmse: 0.238612
[40]    train's rmse: 0.230279  valid's rmse: 0.228192
[60]    train's rmse: 0.224487  valid's rmse: 0.222723
[80]    train's rmse: 0.221184  valid's rmse: 0.219818
[100]   train's rmse: 0.219128  valid's rmse: 0.218168
[120]   train's rmse: 0.217705  valid's rmse: 0.217147
[140]   train's rmse: 0.216601  valid's rmse: 0.216484
[160]   train's rmse: 0.215707  valid's rmse: 0.216011
[180]   train's rmse: 0.214928  valid's rmse: 0.215665
[200]   train's rmse: 0.214236  valid's rmse: 0.215395
[220]   train's rmse: 0.213584  valid's rmse: 0.215153
[240]   train's rmse: 0.21298   valid's rmse: 0.214949
[260]   train's rmse: 0.212409  valid's rmse: 0.214772
[280]   train's rmse: 0.211868  valid's rmse: 0.214607
[300]   train's rmse: 0.211358  valid's rmse: 0.214481
[320]   train's rmse: 0.210863  valid's rmse: 0.214358
[340]   train's rmse: 0.210379  valid's rmse: 0.214244
[360]   train's rmse: 0.209909  valid's rmse: 0.214146
[380]   train's rmse: 0.209458  valid's rmse: 0.214056
[400]   train's rmse: 0.209014  valid's rmse: 0.213975
[420]   train's rmse: 0.208585  valid's rmse: 0.213898
[440]   train's rmse: 0.208147  valid's rmse: 0.213825
[460]   train's rmse: 0.207723  valid's rmse: 0.213757
[480]   train's rmse: 0.20731   valid's rmse: 0.213687
[500]   train's rmse: 0.206915  valid's rmse: 0.213628
[520]   train's rmse: 0.206529  valid's rmse: 0.213571
[540]   train's rmse: 0.206148  valid's rmse: 0.213532
[560]   train's rmse: 0.205777  valid's rmse: 0.213478
[580]   train's rmse: 0.205413  valid's rmse: 0.21344
[600]   train's rmse: 0.205069  valid's rmse: 0.213405
[620]   train's rmse: 0.204732  valid's rmse: 0.213376
[640]   train's rmse: 0.204377  valid's rmse: 0.213334
[660]   train's rmse: 0.204056  valid's rmse: 0.213304
[680]   train's rmse: 0.203728  valid's rmse: 0.213275
[700]   train's rmse: 0.203399  valid's rmse: 0.213244
[720]   train's rmse: 0.203101  valid's rmse: 0.213223
[740]   train's rmse: 0.202808  valid's rmse: 0.213201
[760]   train's rmse: 0.202523  valid's rmse: 0.213175
[780]   train's rmse: 0.202217  valid's rmse: 0.21315
[800]   train's rmse: 0.201915  valid's rmse: 0.21312
[820]   train's rmse: 0.201636  valid's rmse: 0.213104
[840]   train's rmse: 0.201339  valid's rmse: 0.213079
[860]   train's rmse: 0.201044  valid's rmse: 0.213051
[880]   train's rmse: 0.200788  valid's rmse: 0.213044
[900]   train's rmse: 0.200532  valid's rmse: 0.213036
[920]   train's rmse: 0.200271  valid's rmse: 0.213024
[940]   train's rmse: 0.20001   valid's rmse: 0.213017
[960]   train's rmse: 0.199741  valid's rmse: 0.213002
[980]   train's rmse: 0.199495  valid's rmse: 0.212997
[1000]  train's rmse: 0.199236  valid's rmse: 0.212982
[1020]  train's rmse: 0.198988  valid's rmse: 0.212973
[1040]  train's rmse: 0.198748  valid's rmse: 0.212968
[1060]  train's rmse: 0.198523  valid's rmse: 0.212961
[1080]  train's rmse: 0.198282  valid's rmse: 0.212951
[1100]  train's rmse: 0.198038  valid's rmse: 0.212942
[1120]  train's rmse: 0.197797  valid's rmse: 0.212936
[1140]  train's rmse: 0.19754   valid's rmse: 0.212922
[1160]  train's rmse: 0.197297  valid's rmse: 0.212917
[1180]  train's rmse: 0.197072  valid's rmse: 0.212906
[1200]  train's rmse: 0.196846  valid's rmse: 0.212904
[1220]  train's rmse: 0.196601  valid's rmse: 0.212897
[1240]  train's rmse: 0.196346  valid's rmse: 0.212882
[1260]  train's rmse: 0.19612   valid's rmse: 0.212877
[1280]  train's rmse: 0.195899  valid's rmse: 0.212866
[1300]  train's rmse: 0.195682  valid's rmse: 0.212866
[1320]  train's rmse: 0.19546   valid's rmse: 0.212864
[1340]  train's rmse: 0.195246  valid's rmse: 0.212861
[1360]  train's rmse: 0.195027  valid's rmse: 0.212854
[1380]  train's rmse: 0.194818  valid's rmse: 0.212848
[1400]  train's rmse: 0.194612  valid's rmse: 0.212843
[1420]  train's rmse: 0.194399  valid's rmse: 0.212836
[1440]  train's rmse: 0.194177  valid's rmse: 0.212833
[1460]  train's rmse: 0.193975  valid's rmse: 0.212828
[1480]  train's rmse: 0.193753  valid's rmse: 0.212825
[1500]  train's rmse: 0.193551  valid's rmse: 0.212825
[1520]  train's rmse: 0.193333  valid's rmse: 0.212822
[1540]  train's rmse: 0.193135  valid's rmse: 0.212822
[1560]  train's rmse: 0.19292   valid's rmse: 0.21282
[1580]  train's rmse: 0.192713  valid's rmse: 0.212817
[1600]  train's rmse: 0.192498  valid's rmse: 0.21281
[1620]  train's rmse: 0.192293  valid's rmse: 0.212802
[1640]  train's rmse: 0.192101  valid's rmse: 0.212806
[1660]  train's rmse: 0.191905  valid's rmse: 0.212804
[1680]  train's rmse: 0.191702  valid's rmse: 0.212799
[1700]  train's rmse: 0.191499  valid's rmse: 0.212798
[1720]  train's rmse: 0.191312  valid's rmse: 0.212794
[1740]  train's rmse: 0.191113  valid's rmse: 0.212788
[1760]  train's rmse: 0.190915  valid's rmse: 0.212788
[1780]  train's rmse: 0.190715  valid's rmse: 0.212785
[1800]  train's rmse: 0.190535  valid's rmse: 0.212782
[1820]  train's rmse: 0.19034   valid's rmse: 0.212781
[1840]  train's rmse: 0.190171  valid's rmse: 0.212779
[1860]  train's rmse: 0.189979  valid's rmse: 0.212777
[1880]  train's rmse: 0.189796  valid's rmse: 0.212777
[1900]  train's rmse: 0.189607  valid's rmse: 0.212776
[1920]  train's rmse: 0.189429  valid's rmse: 0.212776
[1940]  train's rmse: 0.189238  valid's rmse: 0.212777
[1960]  train's rmse: 0.18904   valid's rmse: 0.212772
[1980]  train's rmse: 0.188838  valid's rmse: 0.212769
[2000]  train's rmse: 0.188652  valid's rmse: 0.212768
[2020]  train's rmse: 0.188473  valid's rmse: 0.21277
[2040]  train's rmse: 0.188283  valid's rmse: 0.212761
[2060]  train's rmse: 0.188102  valid's rmse: 0.212761
[2080]  train's rmse: 0.187902  valid's rmse: 0.212758
[2100]  train's rmse: 0.18772   valid's rmse: 0.212759
[2120]  train's rmse: 0.187533  valid's rmse: 0.212758
[2140]  train's rmse: 0.187347  valid's rmse: 0.212752
[2160]  train's rmse: 0.187137  valid's rmse: 0.212751
[2180]  train's rmse: 0.186956  valid's rmse: 0.212752
Early stopping, best iteration is:
[2131]  train's rmse: 0.187424  valid's rmse: 0.212751
'''

