import json
from lib.couchbase_helper.tuq_helper import N1QLHelper
from lib.membase.api.rest_client import RestConnection
from lib.testconstants import STANDARD_BUCKET_PORT
from pytests.eventing.eventing_constants import HANDLER_CODE
from pytests.eventing.eventing_base import EventingBaseTest
import logging

log = logging.getLogger()


class EventingVolume(EventingBaseTest):
    def setUp(self):
        super(EventingVolume, self).setUp()
        # Un-deploy and delete all the functions
        self.undeploy_delete_all_functions()
        self.dst_bucket_name2 = self.input.param('dst_bucket_name2', 'dst_bucket2')
        self.worker_count = self.input.param('worker_count', 3)
        self.cpp_worker_thread_count = self.input.param('cpp_worker_thread_count', 3)
        # self.rest.set_service_memoryQuota(service='memoryQuota', memoryQuota=3000)
        self.rest.set_service_memoryQuota(service='memoryQuota', memoryQuota=700)
        if self.create_functions_buckets:
            # self.bucket_size = 500
            # self.meta_bucket_size = 100
            self.bucket_size = 100
            self.meta_bucket_size = 100
            bucket_params = self._create_bucket_params(server=self.server, size=self.bucket_size,
                                                       replicas=self.num_replicas)
            bucket_params_meta = self._create_bucket_params(server=self.server, size=self.meta_bucket_size,
                                                       replicas=self.num_replicas)
            self.cluster.create_standard_bucket(name=self.src_bucket_name, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.src_bucket = RestConnection(self.master).get_buckets()
            self.cluster.create_standard_bucket(name=self.dst_bucket_name, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.cluster.create_standard_bucket(name=self.dst_bucket_name1, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.cluster.create_standard_bucket(name=self.dst_bucket_name2, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.cluster.create_standard_bucket(name=self.metadata_bucket_name, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params_meta)
            self.buckets = RestConnection(self.master).get_buckets()
        self.gens_load = self.generate_docs(self.docs_per_day)
        self.batch_size = 20
        # index is required for delete operation through n1ql
        self.n1ql_node = self.get_nodes_from_services_map(service_type="n1ql")
        self.n1ql_helper = N1QLHelper(shell=self.shell,
                                      max_verify=self.max_verify,
                                      buckets=self.buckets,
                                      item_flag=self.item_flag,
                                      n1ql_port=self.n1ql_port,
                                      full_docs_list=self.full_docs_list,
                                      log=self.log, input=self.input,
                                      master=self.master,
                                      use_rest=True
                                      )
        self.n1ql_helper.create_primary_index(using_gsi=True, server=self.n1ql_node)

    def tearDown(self):
        try:
            self.cleanup_eventing()
        except:
            # This is just a cleanup API. Ignore the exceptions.
            pass
        super(EventingVolume, self).tearDown()

    def test_eventing_volume(self):
        # Load data on source bucket
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size)
        # Deploy all the functions
        functions = self.deploy_all_the_functions()
        # Wait for bootstrap to complete for all the functions
        self.wait_for_all_boostrap_to_complete(functions)
        # Validate the results of all the functions deployed
        self.verify_eventing_results_of_all_functions(docs_expected=self.docs_per_day * 2016, verify_results=False)
        # Load data on source bucket
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size, op_type='delete')
        # Validate the results of all the functions deployed
        self.verify_eventing_results_of_all_functions(docs_expected=0, verify_results=False)
        # Undeploy and delete all the functions
        self.undeploy_delete_all_functions()

    def deploy_all_the_functions(self):
        # deploy the first function
        body1 = self.create_save_function_body(self.function_name + "_bucket_op",
                                               HANDLER_CODE.BUCKET_OPS_ON_UPDATE,
                                               worker_count=self.worker_count,
                                               cpp_worker_thread_count=self.cpp_worker_thread_count)
        self.deploy_function(body1, wait_for_bootstrap=False)
        # deploy the second function
        body2 = self.create_save_function_body(self.function_name + "_bucket_op_with_timers",
                                               HANDLER_CODE.BUCKET_OPS_WITH_TIMERS,
                                               worker_count=self.worker_count,
                                               cpp_worker_thread_count=self.cpp_worker_thread_count)
        # this is required to deploy multiple functions at the same time
        del body2['depcfg']['buckets'][0]
        body2['depcfg']['buckets'].append({"alias": self.dst_bucket_name, "bucket_name": self.dst_bucket_name1})
        self.deploy_function(body2, wait_for_bootstrap=False)
        # deploy the third function
        body3 = self.create_save_function_body(self.function_name + "_n1ql_op_with_timers",
                                               HANDLER_CODE.N1QL_OPS_WITH_TIMERS,
                                               worker_count=self.worker_count,
                                               cpp_worker_thread_count=self.cpp_worker_thread_count)
        # this is required to deploy multiple functions at the same time
        del body3['depcfg']['buckets'][0]
        body3['depcfg']['buckets'].append({"alias": self.dst_bucket_name, "bucket_name": self.dst_bucket_name2})
        self.deploy_function(body3, wait_for_bootstrap=False)
        body = [body1, body2, body3]
        return body

    def wait_for_all_boostrap_to_complete(self, functions):
        for function_name in functions:
            self.wait_for_bootstrap_to_complete(function_name['appname'])

    def verify_eventing_results_of_all_functions(self, docs_expected, verify_results=True):
        if verify_results:
            # Verify the results of all the buckets
            self.verify_eventing_results(self.function_name, docs_expected, skip_stats_validation=True)
            self.verify_eventing_results(self.function_name, docs_expected, skip_stats_validation=True,
                                         bucket=self.dst_bucket_name1)
            self.verify_eventing_results(self.function_name, docs_expected, skip_stats_validation=True,
                                         bucket=self.dst_bucket_name2)
        else:
            # Just print the stats after sleeping for 10 mins. Required to get the latest stats.
            self.sleep(600)
            eventing_nodes = self.get_nodes_from_services_map(service_type="eventing", get_all_nodes=True)
            for eventing_node in eventing_nodes:
                rest_conn = RestConnection(eventing_node)
                out = rest_conn.get_all_eventing_stats()
                log.info("Stats for Node {0} is \n{1} ".format(eventing_node.ip, json.dumps(out, sort_keys=True,
                                                                                            indent=4)))
            for bucket in [self.dst_bucket_name, self.dst_bucket_name1, self.dst_bucket_name2]:
                stats_dst = self.rest.get_bucket_stats(bucket)
                log.info("Number of docs in {0} bucket actual : {1} expected : {2} ".format(bucket,
                                                                                            stats_dst["curr_items"],
                                                                                            docs_expected))



