import os
import shutil


def ensure_json_in_appdata():
    appdata_path = os.getenv('APPDATA')
    dsmediaplay_folder = os.path.join(appdata_path, 'dsmediaplay')

    if not os.path.exists(dsmediaplay_folder):
        os.makedirs(dsmediaplay_folder)

    script_directory = os.path.dirname(os.path.abspath(__file__))
    source_file = os.path.join(script_directory, 'login.json')
    destination_file = os.path.join(dsmediaplay_folder, 'login.json')

    if not os.path.exists(destination_file):
        shutil.copy(source_file, destination_file)
        print(f'Copied {source_file} to {destination_file}')
    else:
        print(f'{destination_file} already exists')

    return destination_file


if __name__ == "__main__":
    json_file = ensure_json_in_appdata()
    print(json_file)
