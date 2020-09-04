#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable-msg=line-too-long
"""Module to execute operations related to ISODB data handling"""
import os
import sys
import pprint
import json
import time
import copy
import requests
import click
import git

from config import API_HOST, DOI_MAPPING_PATH, SCRIPT_PATH, canonical_keys, JSON_FOLDER, HEADERS, doi_stub_rules, json_writer, pressure_units
from bibliography_operations import generate_bibliography, regenerate_bibliography
from adsorbents_operations import fix_adsorbent_id, regenerate_adsorbents
from adsorbates_operations import fix_adsorbate_id, regenerate_adsorbates


@click.group()
def cli():
    # pylint: disable=unnecessary-pass
    """Master for click"""
    pass


@cli.command('tester')
def tester_fcn():
    """Test Platform for code reorganization"""
    print('in tester function')
    print(API_HOST)
    print(canonical_keys)


@cli.command('clean_json')
@click.argument('filename', type=click.Path(exists=True), nargs=1)
def clean_json(filename):
    """Read in JSON and output according to ISODB specs"""
    print('operate on filename: ', filename)
    with open(filename, mode='r') as infile:
        isotherm_data = json.load(infile)
    os.rename(filename, filename + '.bak')
    json_writer(filename, isotherm_data)
    os.remove(filename + '.bak')


@cli.command('download_isotherm')
@click.argument('isotherm', nargs=1)
def download_isotherm(isotherm):
    """Download a specific isotherm from the ISODB and format to ISODB specs"""
    if isotherm[-5:] != '.json':
        isotherm += '.json'
    print('Downloading Isotherm: ', isotherm)
    url = API_HOST + '/isodb/api/isotherm/' + isotherm
    isotherm_data = json.loads(requests.get(url, headers=HEADERS).content)
    json_writer(isotherm, isotherm_data)


@cli.command('regenerate_library')
def regenerate_isotherm_library():
    """Generate the entire ISODB library from the API"""
    # Create the JSON Library folder if necessary
    if not os.path.exists(JSON_FOLDER):
        os.mkdir(JSON_FOLDER)

    # Generate a DOI list from the ISODB API
    url = API_HOST + '/isodb/api/biblio.json'
    bibliography = json.loads(requests.get(url, headers=HEADERS).content)
    print(len(bibliography), 'Bibliography Entries')

    # Count isotherms for DOIs in the database
    url = API_HOST + '/isodb/api/isotherms.json'
    isotherms_list = json.loads(requests.get(url, headers=HEADERS).content)
    isotherm_count = {}
    for isotherm in isotherms_list:
        doi = isotherm['DOI'].lower()
        if doi not in isotherm_count:
            isotherm_count[doi] = 1
        else:
            isotherm_count[doi] += 1
    print(len(isotherms_list), 'Isotherm Files')

    # Create a CSV file with the DOI -> folder mapping
    doi_mapping = open(DOI_MAPPING_PATH, mode='w')
    doi_mapping.write('DOI,  "DOI_Stub"\n')

    # Download and Organize the Isotherms
    article_count = 0
    for article in bibliography:
        # print(article["isotherms"])

        # Shorten the DOI according to rules specified in global variables
        doi = article['DOI']
        doi_stub = article['DOI']
        for rule in doi_stub_rules:
            doi_stub = doi_stub.replace(rule['old'], rule['new'])

        num_isotherms = len(article['isotherms'])
        # print(doi, doi_stub, num_isotherms)

        # Download the isotherms
        if num_isotherms > 0:
            article_count += 1
            doi_folder = os.path.join(JSON_FOLDER, doi_stub)
            # print(doi_folder)
            if not os.path.exists(doi_folder):
                os.mkdir(doi_folder)
            doi_mapping.write(doi + ', ' + doi_stub + '\n')

            for isotherm in article['isotherms']:
                url = API_HOST + '/isodb/api/isotherm/' + isotherm[
                    'filename'] + '.json'
                isotherm_json = json.loads(
                    requests.get(url, headers=HEADERS).content)
                # print(json.dumps(isotherm_json, sort_keys=True))
                filename = os.path.join(doi_folder,
                                        isotherm['filename'] + '.json')
                # print(filename)
                json_writer(filename, isotherm_json)
                # break
            print(doi, 'Finished')

            # break

        # if article_count > 50: break
        if article_count % 10 == 0:
            time.sleep(5)  # slow down API calls to not overwhelm the server
        # break

    print(article_count, 'Objects with Isotherms')
    doi_mapping.close()


@cli.command('regenerate_adsorbents')
def regenerate_adsorbents_runner():
    """Run the regenerate adsorbents function"""
    regenerate_adsorbents()


@cli.command('regenerate_adsorbates')
def regenerate_adsorbates_runner():
    """Run the regenerate adsorbates function"""
    regenerate_adsorbates()


@cli.command('regenerate_bibliography')
def regenerate_bibliography_runner():
    """Run the regenerate bibliography function"""
    regenerate_bibliography()


@cli.command('git_log')
def git_log():
    """parse the git log"""
    print('parsing the git log')
    repo = git.Repo(SCRIPT_PATH)
    commits = list(repo.iter_commits('master', max_count=5))
    for commit in commits:
        print(commit.message)


def default_adsorption_units(input_units):
    """convert units from input units to bar"""
    # Generate units lookup tables from API
    url = API_HOST + '/isodb/api/default-adsorption-unit-lookup.json'
    default_units = json.loads(requests.get(url, headers=HEADERS).content)
    url = API_HOST + '/isodb/api/adsorption-unit-lookup.json'
    all_units = json.loads(requests.get(url, headers=HEADERS).content)
    # input -> ID -> output mapping
    units_id = next(item for item in all_units
                    if item['name'].lower() == input_units.lower())['id']
    output = next(item for item in default_units
                  if item['id'] == units_id)['name']
    return output


@cli.command('post_process')
@click.argument('filename', type=click.Path(exists=True), nargs=1)
def post_process(filename):
    # pylint: disable-msg=too-many-locals
    # pylint: disable-msg=too-many-branches
    # pylint: disable-msg=too-many-statements
    """Function to process raw isotherm to ISDOB upload format"""
    with open(filename, mode='r') as infile:
        isotherm = json.load(infile)
    print('before')
    pprint.pprint(isotherm)
    # Check for adsorbate InChIKey(s)
    #  a. isotherm metadata
    adsorbates = isotherm['adsorbates']
    for (i, adsorbate) in enumerate(adsorbates):
        if 'InChIKey' not in adsorbate:
            # Correct the gas ID using the ISODB API
            adsorbate, check = fix_adsorbate_id(adsorbate)
            if not check:
                print('UNKNOWN ADSORBATE: ', adsorbate, filename)
                sys.exit()
            else:
                adsorbates[i] = adsorbate
        else:
            # Confirm that the InChIKey is in the ISODB
            url = API_HOST + '/isodb/api/gases.json'
            adsorbates_list = json.loads(
                requests.get(url, headers=HEADERS).content)
            adsorbate_inchikeys = [x['InChIKey'] for x in adsorbates_list]
            if adsorbate['InChIKey'] not in adsorbate_inchikeys:
                print('new inchikey, create upload file')
                # needs to include inchikey, name  <- double check this!!!!
                # Extract adsorbate dictionary as a new file
                filename = adsorbate['InChIKey'] + '.json'
                json_writer(filename, adsorbate)
    #  b. isotherm data points
    for point in isotherm['isotherm_data']:
        for species in point['species_data']:
            if 'InChIKey' not in species:
                # Correct the gas ID
                adsorbate, check = fix_adsorbate_id({'name': species['name']})
                if not check:
                    print('UNKNOWN ADSORBATE: ', adsorbate, filename)
                    sys.exit()
                else:
                    species['InChIKey'] = adsorbate['InChIKey']
                    del species['name']
    # Check for adsorbent hashkey
    adsorbent = isotherm['adsorbent']
    if 'hashkey' not in adsorbent:
        # Correct the material ID
        material, check = fix_adsorbent_id(adsorbent)
        if not check:
            print('UNKNOWN ADSORBENT: ', adsorbent, filename)
            sys.exit()
        else:
            adsorbent['hashkey'] = material['hashkey']
            adsorbent['name'] = material['name']
    # Convert pressure to bar units
    raw_units = isotherm['pressureUnits']
    if raw_units == 'RELATIVE':
        try:
            p_conversion = isotherm['saturationPressure']
        except:
            raise Exception(
                'RELATIVE pressure units declared; must specify saturationPressure (in bar)'
            )
    else:
        try:
            p_conversion = pressure_units[
                raw_units]  # conversion from raw_units to bar
        except:
            raise Exception('Unknown pressure units: ', raw_units)
    try:
        log_scale = isotherm['log_scale']
    except ValueError:
        log_scale = False
    for point in isotherm['isotherm_data']:
        if log_scale:
            # Convert from log (assume base-10) to bar pressure
            try:
                point['pressure'] = (10.0**point['pressure']) * p_conversion
            except ValueError:
                raise Exception(
                    'ERROR: unable to convert log-scale pressure: ',
                    point['pressure'])
        else:
            # Otherwise, just convert bar pressure
            point['pressure'] = point['pressure'] * p_conversion
    isotherm['pressureUnits'] = 'bar'
    # Map the adsorptionUnits to the default value
    isotherm['adsorptionUnits'] = default_adsorption_units(
        isotherm['adsorptionUnits'])
    # Convert the tabular_data boolean variable to integer (SQL does not support boolean)
    if isotherm['tabular_data'] is True:
        isotherm['tabular_data'] = 1
    elif isotherm['tabular_data'] is False:
        isotherm['tabular_data'] = 0
    elif isotherm['tabular_data'] != 0 and isotherm['tabular_data'] != 1:
        raise ValueError(
            "ERROR: 'tabular_data' field does not conform to either (0,1) or (False,True)"
        )

    # Trim out points with invalid pressure or adsorption
    new_points = []
    for point in isotherm['isotherm_data']:
        yvalues = [species['adsorption'] for species in point['species_data']]
        #  Include points with pressure > 0. or adsorption > 0.
        if point['pressure'] > 0.0 and min(yvalues) > 0.0:
            new_points.append(point)
    isotherm['isotherm_data'] = new_points
    # Clean up unnecessary keys
    for key in copy.copy(isotherm):
        if key not in canonical_keys:
            del isotherm[key]
    # We're finally done, output!
    isotherm['filename'] = 'newfile.json'
    json_writer('newfile.json', isotherm)
    print('after')
    pprint.pprint(isotherm)


# To Do:
# Post-Process Script:
#   Do we want to deal with partial-pressure in the isotherm_data block ?
#     (appears in composition area)
#     DWS: not inclined to error check this block as it requires expert knowledge to compose
#   Handling of new adsorbent materials
#     Digitizer should include option to specify new adsorbent metadata
#   Handling of new adsorbates
#     Digitizer should include option to specify new adsorbate metadata
# Bibliographic entry generator
#   collate data from isotherms
#   if DOI exists, compare expected data to existing DB entry
#     if missing in existing, provide instructions for adding
#     if missing in expected, DO NOT add  [old data in DB is structured this way]
#   copy code from existing notebook for processing student data


@cli.command('generate_bibliography')
@click.argument('folder', type=click.Path(exists=True), nargs=1)
def generate_bibliography_runner(folder):
    """Run the bibliography generator"""
    generate_bibliography(folder)


if __name__ == '__main__':
    cli()  # pylint: disable=no-value-for-parameter