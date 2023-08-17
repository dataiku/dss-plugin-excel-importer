import dataiku
import pandas as pd
import openpyxl
import time
from dataiku.runnables import Runnable, ResultTable
from io import BytesIO


class MyRunnable(Runnable):
    def __init__(self, project_key, config, plugin_config):
        """
        :param project_key: the project in which the runnable executes
        :param config: the dict of the configuration of the object
        :param plugin_config: contains the plugin settings
        """
        self.project_key = project_key
        self.config = config
        self.plugin_config = plugin_config

    def get_progress_target(self):
        return (100, 'FILES')

    def run(self, progress_callback):

        def update_percent(percent, last_update_time):
            new_time = time.time()
            if (new_time - last_update_time) > 3:
                progress_callback(percent)
                return new_time
            else:
                return last_update_time

        # Get project and folder containing the Excel files
        client = dataiku.api_client()
        project = client.get_project(self.project_key)

        folder_id = self.config.get("model_folder_id")
        overwrite = self.config.get("overwrite", False)

        folder = dataiku.Folder(folder_id, project_key=self.project_key)
        folder_paths = folder.list_paths_in_partition()

        macro_creates_dataset = False  # A boolean used to provide an informative message to the user when the macro creates a dataset

        # List the datasets in the project
        datasets_in_project = []
        for dataset in project.list_datasets():
            datasets_in_project.append(dataset.get('name'))

        # Actions performed
        actions_performed = dict()
        num_files = len(folder_paths)

        update_time = time.time()
        for file_index, file_path in enumerate(folder_paths):
            file_name = file_path.strip('/')

            with folder.get_download_stream(file_path) as file_handle:
                ss = openpyxl.load_workbook(BytesIO(file_handle.read()))

            for sheet in ss.sheetnames:
                ss_sheet = ss[sheet]
                title = ss_sheet.title

                # Ensure the file name is in the title for the dataset (prepend if missing)
                if not file_name.split(".")[0] in title:
                    title = file_name.split(".")[0] + "_" + sheet

                title = '_'.join(title.split())
                title = title.replace(')', '')
                title = title.replace('(', '')
                title = title.replace('/', '_')

                create_dataset = True
                if title in datasets_in_project:
                    if overwrite:
                        project.get_dataset(title).delete()
                        actions_performed[title] = "replaced"
                    else:
                        create_dataset = False
                        actions_performed[title] = "skipped (already exists)"
                else:
                    actions_performed[title] = "created"
                    macro_creates_dataset = True
                if create_dataset:
                    dataset = project.create_dataset(
                        title,
                        'FilesInFolder',
                        params={
                            'folderSmartId': folder_id,
                            'filesSelectionRules': {
                                'mode': 'EXPLICIT_SELECT_FILES',
                                'explicitFiles': [file_name]
                            }
                        },
                        formatType='excel',
                        formatParams={"xlsx": True, "sheets": "*" + ss_sheet.title, 'parseHeaderRow': True}
                    )

                    with folder.get_download_stream(file_path) as file_handle:
                        df = pd.read_excel(BytesIO(file_handle.read()), sheet_name=ss_sheet.title, nrows=1000)
                        dataset.set_schema({'columns': [{'name': column, 'type': 'string'} for column, column_type in df.dtypes.items()]})

                percent = 100*float(file_index+1)/num_files
                update_time = update_percent(percent, update_time)

        # Output table
        rt = ResultTable()
        rt.add_column("actions", "Actions", "STRING")

        # Actions : "dataset" has been created or replaced
        for i in range(len(actions_performed)):
            record = []
            record.append(list(actions_performed.keys())[i] + " has been " + list(actions_performed.values())[i])
            rt.add_record(record)

        if macro_creates_dataset:
            rt.add_record(["Please refresh this page to see new datasets."])

        return rt
