import os
import platform

import GPUtil

from fedml.computing.scheduler.comm_utils import sys_utils
from fedml.computing.scheduler.comm_utils.constants import SchedulerConstants
from fedml.computing.scheduler.comm_utils.sys_utils import get_python_program
from fedml.computing.scheduler.model_scheduler.device_model_cache import FedMLModelCache
from fedml.core.common.singleton import Singleton
import threading


class JobRunnerUtils(Singleton):
    def __init__(self):
        if not hasattr(self, "run_id_to_gpu_ids_map"):
            self.run_id_to_gpu_ids_map = dict()
        if not hasattr(self, "available_gpu_ids"):
            self.available_gpu_ids = list()
            self.available_gpu_ids = JobRunnerUtils.get_realtime_gpu_available_ids().copy()
        if not hasattr(self, "lock_available_gpu_ids"):
            self.lock_available_gpu_ids = threading.Lock()

    @staticmethod
    def get_instance():
        return JobRunnerUtils()

    def occupy_gpu_ids(self, run_id, request_gpu_num, inner_id=None):
        self.lock_available_gpu_ids.acquire()

        self.available_gpu_ids = self.search_and_refresh_available_gpu_ids(self.available_gpu_ids)
        if len(self.run_id_to_gpu_ids_map.keys()) <= 0:
            self.available_gpu_ids = self.balance_available_gpu_ids(self.available_gpu_ids)

        cuda_visible_gpu_ids_str, matched_gpu_num, _ = self.request_gpu_ids(
            request_gpu_num, self.available_gpu_ids)
        if cuda_visible_gpu_ids_str is None:
            self.lock_available_gpu_ids.release()
            return None
            # self.available_gpu_ids = self.balance_available_gpu_ids(self.available_gpu_ids)
            # cuda_visible_gpu_ids_str, matched_gpu_num, _ = self.request_gpu_ids(
            #     request_gpu_num, self.available_gpu_ids)
            # if cuda_visible_gpu_ids_str is None:
            #     self.lock_available_gpu_ids.release()
            #     return None

        self.run_id_to_gpu_ids_map[str(run_id)] = self.available_gpu_ids[0:matched_gpu_num].copy()
        self.available_gpu_ids = self.available_gpu_ids[matched_gpu_num:].copy()
        self.available_gpu_ids = list(dict.fromkeys(self.available_gpu_ids))

        FedMLModelCache.get_instance().set_redis_params()
        FedMLModelCache.get_instance().set_global_available_gpu_ids(self.available_gpu_ids)

        if inner_id is not None:
            FedMLModelCache.get_instance().set_redis_params()
            FedMLModelCache.get_instance().set_end_point_gpu_resources(
                inner_id, matched_gpu_num, cuda_visible_gpu_ids_str)

        self.lock_available_gpu_ids.release()

        return cuda_visible_gpu_ids_str

    @staticmethod
    def search_and_refresh_available_gpu_ids(available_gpu_ids):
        trimmed_gpu_ids = JobRunnerUtils.trim_unavailable_gpu_ids(available_gpu_ids)
        # if len(trimmed_gpu_ids) <= 0:
        #     available_gpu_ids = JobRunnerUtils.balance_available_gpu_ids(trimmed_gpu_ids)
        return trimmed_gpu_ids

    @staticmethod
    def balance_available_gpu_ids(available_gpu_ids):
        gpu_list, realtime_available_gpu_ids = JobRunnerUtils.get_gpu_list_and_realtime_gpu_available_ids()
        available_gpu_ids = realtime_available_gpu_ids
        if len(available_gpu_ids) <= 0:
            for gpu in gpu_list:
                gpu = GPUtil.GPU(gpu)
                if gpu.memoryUtil > 0.8:
                    continue
                available_gpu_ids.append(gpu.id)

        return available_gpu_ids.copy()

    @staticmethod
    def request_gpu_ids(request_gpu_num, available_gpu_ids):
        available_gpu_count = len(available_gpu_ids)
        request_gpu_num = 0 if request_gpu_num is None else request_gpu_num
        matched_gpu_num = min(available_gpu_count, request_gpu_num)
        if matched_gpu_num <= 0 or matched_gpu_num != request_gpu_num:
            return None, None, None

        matched_gpu_ids = map(lambda x: str(x), available_gpu_ids[0:matched_gpu_num])
        cuda_visible_gpu_ids_str = ",".join(matched_gpu_ids)
        return cuda_visible_gpu_ids_str, matched_gpu_num, matched_gpu_ids

    @staticmethod
    def trim_unavailable_gpu_ids(gpu_ids):
        # Trim the gpu ids based on the realtime available gpu id list.
        gpu_list, realtime_available_gpu_ids = JobRunnerUtils.get_gpu_list_and_realtime_gpu_available_ids()
        unavailable_gpu_ids = list()
        for index, gpu_id in enumerate(gpu_ids):
            if int(gpu_id) not in realtime_available_gpu_ids:
                unavailable_gpu_ids.append(index)

        trimmed_gpu_ids = [gpu_id for index, gpu_id in enumerate(gpu_ids) if index not in unavailable_gpu_ids]

        return trimmed_gpu_ids.copy()

    def release_gpu_ids(self, run_id):
        self.lock_available_gpu_ids.acquire()
        occupy_gpu_id_list = self.run_id_to_gpu_ids_map.get(str(run_id), [])
        self.available_gpu_ids.extend(occupy_gpu_id_list.copy())
        self.available_gpu_ids = list(dict.fromkeys(self.available_gpu_ids))
        if self.run_id_to_gpu_ids_map.get(str(run_id)) is not None:
            self.run_id_to_gpu_ids_map.pop(str(run_id))

        FedMLModelCache.get_instance().set_redis_params()
        FedMLModelCache.get_instance().set_global_available_gpu_ids(self.available_gpu_ids)

        self.lock_available_gpu_ids.release()

    def get_available_gpu_id_list(self):
        self.lock_available_gpu_ids.acquire()
        ret_gpu_ids = self.available_gpu_ids.copy()
        self.lock_available_gpu_ids.release()
        return ret_gpu_ids

    @staticmethod
    def get_realtime_gpu_available_ids():
        gpu_list = sys_utils.get_gpu_list()
        gpu_count = len(gpu_list)
        realtime_available_gpu_ids = sys_utils.get_available_gpu_id_list(limit=gpu_count)
        return realtime_available_gpu_ids

    @staticmethod
    def get_gpu_list_and_realtime_gpu_available_ids():
        gpu_list = sys_utils.get_gpu_list()
        gpu_count = len(gpu_list)
        realtime_available_gpu_ids = sys_utils.get_available_gpu_id_list(limit=gpu_count)
        return gpu_list, realtime_available_gpu_ids

    @staticmethod
    def generate_job_execute_commands(run_id, edge_id, version,
                                      package_type, executable_interpreter, entry_file_full_path,
                                      conf_file_object, entry_args, assigned_gpu_ids,
                                      job_api_key, client_rank, job_yaml=None, request_gpu_num=None,
                                      scheduler_match_info=None, cuda_visible_gpu_ids_str=None):
        shell_cmd_list = list()
        entry_commands_origin = list()
        computing = job_yaml.get("computing", {})
        request_gpu_num = computing.get("minimum_num_gpus", None) if request_gpu_num is None else request_gpu_num

        # Read entry commands if job is from launch
        if package_type == SchedulerConstants.JOB_PACKAGE_TYPE_LAUNCH or \
                os.path.basename(entry_file_full_path) == SchedulerConstants.LAUNCH_JOB_DEFAULT_ENTRY_NAME:
            with open(entry_file_full_path, 'r') as entry_file_handle:
                entry_commands_origin.extend(entry_file_handle.readlines())
                entry_file_handle.close()

        # Generate the export env list for publishing environment variables
        export_cmd = "set" if platform.system() == "Windows" else "export"
        export_config_env_list, config_env_name_value_map = JobRunnerUtils.parse_config_args_as_env_variables(
            export_cmd, conf_file_object)

        # Generate the export env list about scheduler matching info for publishing environment variables
        export_match_env_list, match_env_name_value_map = \
            JobRunnerUtils.assign_matched_resources_to_run_and_generate_envs(
                run_id, export_cmd, scheduler_match_info
            )

        # Replace entry commands with environment variable values
        entry_commands = JobRunnerUtils.replace_entry_command_with_env_variable(
            entry_commands_origin, config_env_name_value_map
        )
        entry_commands = JobRunnerUtils.replace_entry_command_with_env_variable(
            entry_commands, match_env_name_value_map
        )

        # Replace entry arguments with environment variable values
        entry_args = JobRunnerUtils.replace_entry_args_with_env_variable(entry_args, config_env_name_value_map)
        entry_args = JobRunnerUtils.replace_entry_args_with_env_variable(entry_args, match_env_name_value_map)

        # Add the export env list to the entry commands
        for config_env_cmd in export_config_env_list:
            entry_commands.insert(0, config_env_cmd)
        for match_env_cmd in export_match_env_list:
            entry_commands.insert(0, match_env_cmd)

        # Add general environment variables
        entry_commands.insert(0, f"{export_cmd} FEDML_CURRENT_EDGE_ID={edge_id}\n")
        entry_commands.insert(0, f"{export_cmd} FEDML_CURRENT_RUN_ID={run_id}\n")
        entry_commands.insert(0, f"{export_cmd} FEDML_CURRENT_VERSION={version}\n")
        entry_commands.insert(0, f"{export_cmd} FEDML_ENV_VERSION={version}\n")
        entry_commands.insert(0, f"{export_cmd} FEDML_USING_MLOPS=true\n")
        entry_commands.insert(0, f"{export_cmd} FEDML_CLIENT_RANK={client_rank}\n")
        if job_api_key is not None and str(job_api_key).strip() != "":
            entry_commands.insert(0, f"{export_cmd} FEDML_RUN_API_KEY={job_api_key}\n")
        if cuda_visible_gpu_ids_str is not None and str(cuda_visible_gpu_ids_str).strip() != "":
            entry_commands.insert(0, f"{export_cmd} CUDA_VISIBLE_DEVICES={cuda_visible_gpu_ids_str}\n")
        print(f"cuda_visible_gpu_ids_str {cuda_visible_gpu_ids_str}")

        # Set -e for the entry script
        entry_commands_filled = list()
        if platform.system() == "Windows":
            entry_file_full_path = entry_file_full_path.rstrip(".sh") + ".bat"
            for cmd in entry_commands:
                entry_commands_filled.append(cmd)
                entry_commands_filled.append("if %ERRORLEVEL% neq 0 EXIT %ERRORLEVEL%\n")
            entry_commands_filled.append("EXIT %ERRORLEVEL%")
        else:
            entry_commands_filled = entry_commands
            entry_commands_filled.insert(0, "set -e\n")

        # If the job type is not launch, we need to generate an entry script wrapping with entry commands
        if package_type != SchedulerConstants.JOB_PACKAGE_TYPE_LAUNCH and \
                os.path.basename(entry_file_full_path) != SchedulerConstants.LAUNCH_JOB_DEFAULT_ENTRY_NAME:
            if str(entry_file_full_path).endswith(".sh"):
                shell_program = SchedulerConstants.CLIENT_SHELL_BASH
            elif str(entry_file_full_path).endswith(".py"):
                shell_program = get_python_program()
            elif str(entry_file_full_path).endswith(".bat"):
                shell_program = SchedulerConstants.CLIENT_SHELL_PS
            entry_commands_filled.append(f"{shell_program} {entry_file_full_path} {entry_args}\n")
            entry_file_full_path = os.path.join(
                os.path.dirname(entry_file_full_path), os.path.basename(entry_file_full_path) + ".sh")

        # Write the entry commands to the entry script
        with open(entry_file_full_path, 'w') as entry_file_handle:
            entry_file_handle.writelines(entry_commands_filled)
            entry_file_handle.close()

        # Generate the shell commands to be executed
        shell_cmd_list.append(f"{executable_interpreter} {entry_file_full_path}")

        return shell_cmd_list

    @staticmethod
    def replace_entry_command_with_env_variable(entry_commands, env_name_value_map):
        entry_commands_replaced = list()
        for entry_cmd in entry_commands:
            for env_name, env_value in env_name_value_map.items():
                if platform.system() == "Windows":
                    entry_cmd = entry_cmd.replace(f"%{env_name}%", str(env_value))
                else:
                    entry_cmd = entry_cmd.replace(f"${{{env_name}}}", str(env_value))
                    entry_cmd = entry_cmd.replace(f"${env_name}", str(env_value))

            entry_commands_replaced.append(entry_cmd)

        return entry_commands_replaced

    @staticmethod
    def replace_entry_args_with_env_variable(entry_args, env_name_value_map):
        if entry_args is None:
            return ""
        for env_name, env_value in env_name_value_map.items():
            if platform.system() == "Windows":
                entry_args = entry_args.replace(f"%{env_name}%", str(env_value))
            else:
                entry_args = entry_args.replace(f"${{{env_name}}}", str(env_value))
                entry_args = entry_args.replace(f"${env_name}", str(env_value))

        return entry_args

    @staticmethod
    def parse_config_args_as_env_variables(export_cmd, run_params):
        export_env_command_list, env_name_value_map = JobRunnerUtils.get_env_from_dict(
            export_cmd, run_params
        )

        return export_env_command_list, env_name_value_map

    @staticmethod
    def get_env_from_dict(
            export_cmd, config_dict, export_env_command_list=[], env_name_value_map=dict(),
            config_key_path=""
    ):
        if config_dict == {}:
            return {}

        for config_key, config_value in config_dict.items():
            if isinstance(config_value, dict):
                JobRunnerUtils.get_env_from_dict(
                    export_cmd, config_value, export_env_command_list=export_env_command_list,
                    env_name_value_map=env_name_value_map, config_key_path=config_key
                )
            else:
                env_name = f"FEDML_ENV_{'' if config_key_path == '' else str(config_key_path).upper()+'_' }" \
                           f"{str(config_key).upper()}"
                config_value = str(config_value).replace("\n", ";")
                config_value = str(config_value).replace("\"", "\\\"")
                export_env_command_list.append(f"{export_cmd} {env_name}=\"{config_value}\"\n")
                env_name_value_map[env_name] = config_value

        return export_env_command_list, env_name_value_map

    @staticmethod
    def assign_matched_resources_to_run_and_generate_envs(run_id, export_cmd, scheduler_match_info):
        if scheduler_match_info is None:
            scheduler_match_info = {}
        master_node_addr = scheduler_match_info.get("master_node_addr", "localhost")
        master_node_port = scheduler_match_info.get(
            "master_node_port", SchedulerConstants.JOB_MATCH_DEFAULT_MASTER_NODE_PORT)
        num_nodes = scheduler_match_info.get("num_nodes", 1)
        matched_gpu_num = scheduler_match_info.get("matched_gpu_num", 0)
        matched_gpu_ids = scheduler_match_info.get("matched_gpu_ids", None)
        matched_gpu_num = 1 if matched_gpu_num <= 0 else matched_gpu_num

        export_env_command_list = list()
        env_name_value_map = dict()

        if master_node_addr is not None and str(master_node_addr).strip() != "":
            export_env_command_list.append(f"{export_cmd} FEDML_NODE_0_ADDR={master_node_addr}\n")
            env_name_value_map["FEDML_NODE_0_ADDR"] = master_node_addr

        if master_node_port is not None and str(master_node_port).strip() != "":
            export_env_command_list.append(f"{export_cmd} FEDML_NODE_0_PORT={master_node_port}\n")
            env_name_value_map["FEDML_NODE_0_PORT"] = master_node_port

        if num_nodes is not None and str(num_nodes).strip() != "":
            export_env_command_list.append(f"{export_cmd} FEDML_NUM_NODES={num_nodes}\n")
            env_name_value_map["FEDML_NUM_NODES"] = num_nodes

        return export_env_command_list, env_name_value_map
