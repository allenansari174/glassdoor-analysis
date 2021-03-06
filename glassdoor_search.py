import os
import json
import pandas as pd
import socket
import requests
from time import sleep
from multiprocessing import Pool, cpu_count
from progressbar import ProgressBar
from pymongo import MongoClient


# glassdoor API documentation = https://www.glassdoor.com/developer/index.htm
def glassdoor_search(action='employers', page=1):
    '''
    Function to populate MongoDB with data from Glassdoor API. Currently
    only works for glassdoor's Employers API.

    INPUT:
        action: str, section of API to search
        page: int, page of results

    OUTPUT:
        data: JSON object with employer metadata
    '''

    url = 'http://api.glassdoor.com/api/api.htm?'
    params = {'v': '1',
              't.p': os.environ['GLASSDOOR_ID'],
              't.k': os.environ['GLASSDOOR_KEY'],
              'userip': socket.gethostbyname(socket.gethostname()),
              'useragent': 'Mozilla/5.0',
              'action': action,
              'pn': page}
    url = url + \
        't.p={}&t.k={}&userip={}&useragent={}&format=json&v={}&action={}&pn={}'.format(
            params['t.p'],
            params['t.k'],
            params['userip'],
            params['useragent'],
            params['v'],
            params['action'],
            params['pn'])
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    if response.status_code != 200:
        sleep(15)
        data = glassdoor_search(action, page)
    else:
        data = json.loads(response.text)
    return data


def scrape_api_page(page_num):
    '''
    Function to scrape every page of glassdoor's employers API

    INPUT:
        page_num: page number of API to scrape

    OUTPUT:
        None
    '''
    page = glassdoor_search('employers', page_num)
    counter = 1
    while not page['success'] and counter < 5:
        page = glassdoor_search('employers', page_num)
        counter += 1
    else:
        employers = page['response']['employers']
    return employers


def multi_core_scrape(num_pages, db_coll):
    '''
    Map the API scrape across number of processors - 1 for performance boost.

    INPUT:
        num_pages: int, number of pages to scrape
        db_coll: pymongo collection object, collection to add documents to

    OUTPUT:
        None, records inserted into MongoDB
    '''
    cpus = cpu_count() - 1
    pool = Pool(processes=cpus)
    pages = range(1, num_pages + 1)
    employers = pool.map(scrape_api_page, pages)
    pool.close()
    pool.join()
    print 'Inserting Employer Records into MongoDB . . .'
    pbar = ProgressBar()
    for page in pbar(employers):
        db_coll.insert_many(page)


def empty_df():
    '''
    Function to create an empty pandas DataFrame object (used in mongo_to_pandas)

    INPUT: None

    OUTPUT: empty pandas DataFrame object
    '''
    df = pd.DataFrame(columns=['company_id',
                               'company_name',
                               'num_ratings',
                               'overall_rating',
                               'recommend_pct',
                               'culture_rating',
                               'comp_rating',
                               'opportunity_rating',
                               'leader_rating',
                               'work_life_rating',
                               'industry'])
    return df


def parse_record(rec):
    '''
    Function to parse Mongo record into a pandas Series object

    INPUT:
        rec: record from MongoDB

    OUTPUT:
        row: Mongo record converted to pandas Series
    '''
    row = {'company_id': rec.get('id', None),
           'company_name': rec.get('name', None),
           'num_ratings': rec.get('numberOfRatings', None),
           'overall_rating': rec.get('overallRating', None),
           'recommend_pct': rec.get('recommendToFriendRating', None),
           'culture_rating': rec.get('cultureAndValuesRating', None),
           'comp_rating': rec.get('compensationAndBenefitsRating', None),
           'opportunity_rating': rec.get('careerOpportunitiesRating', None),
           'leader_rating': rec.get('seniorLeadershipRating', None),
           'work_life_rating': rec.get('workLifeBalanceRating', None),
           'industry': rec.get('industryName', None)}
    return pd.Series(row)


def mongo_to_pandas(db_coll):
    '''
    Function to pull key information from a mongo collection into a
    pandas DataFrame

    INPUT:
        db_coll: pymongo collection object

    OUTPUT:
        df: pandas DataFrame object
    '''
    df = empty_df()
    df_2 = empty_df()
    c = db_coll.find()
    lst = list(c)
    i = 0
    pbar = ProgressBar()
    print 'Loading DataFrame from MongoDB . . .'
    for rec in pbar(lst):
        i += 1
        if i % 2500 == 0:
            df = df.append(df_2)
            df_2 = empty_df()
        row = parse_record(rec)
        df_2 = df_2.append(row, ignore_index=True)
    df = df.append(df_2)
    df['company_id'] = df['company_id'].astype(int)
    df['overall_rating'] = df['overall_rating'].astype(float)
    df['culture_rating'] = df['culture_rating'].astype(float)
    df['comp_rating'] = df['comp_rating'].astype(float)
    df['opportunity_rating'] = df['opportunity_rating'].astype(float)
    df['leader_rating'] = df['leader_rating'].astype(float)
    df['work_life_rating'] = df['work_life_rating'].astype(float)
    df['num_ratings'] = df['num_ratings'].astype(int)
    return df


if __name__ == '__main__':
    init_search = glassdoor_search()
    num_pages = init_search['response']['totalNumberOfPages']

    db_client = MongoClient()
    db = db_client['glassdoor']
    emp_coll = db['employers']

    multi_core_scrape(num_pages, emp_coll)

    employers_df = mongo_to_pandas(emp_coll)
    employers_df.to_pickle(os.path.join('data', 'employers.pkl'))
