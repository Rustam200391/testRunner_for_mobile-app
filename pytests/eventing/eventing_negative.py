import json

from lib.couchbase_helper.documentgenerator import BlobGenerator, JsonDocGenerator
from lib.membase.api.rest_client import RestConnection
from lib.testconstants import STANDARD_BUCKET_PORT
from couchbase.bucket import Bucket
from pytests.eventing.eventing_constants import HANDLER_CODE, HANDLER_CODE_ERROR
from pytests.eventing.eventing_base import EventingBaseTest
import logging

log = logging.getLogger()


class EventingNegative(EventingBaseTest):
    def setUp(self):
        super(EventingNegative, self).setUp()
        if self.create_functions_buckets:
            self.bucket_size = 100
            log.info(self.bucket_size)
            bucket_params = self._create_bucket_params(server=self.server, size=self.bucket_size,
                                                       replicas=self.num_replicas)
            self.cluster.create_standard_bucket(name=self.src_bucket_name, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.src_bucket = RestConnection(self.master).get_buckets()
            self.cluster.create_standard_bucket(name=self.dst_bucket_name, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.cluster.create_standard_bucket(name=self.metadata_bucket_name, port=STANDARD_BUCKET_PORT + 1,
                                                bucket_params=bucket_params)
            self.buckets = RestConnection(self.master).get_buckets()
        self.gens_load = self.generate_docs(self.docs_per_day)
        self.expiry = 3

    def tearDown(self):
        super(EventingNegative, self).tearDown()

    def test_delete_function_when_function_is_in_deployed_state_and_which_is_already_deleted(self):
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size)
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.BUCKET_OPS_ON_UPDATE, worker_count=3)
        self.deploy_function(body)
        # Wait for eventing to catch up with all the create mutations and verify results
        self.verify_eventing_results(self.function_name, self.docs_per_day * 2016)
        # Try deleting a function which is still in deployed state
        try:
            self.delete_function(body)
        except Exception as ex:
            log.info("output from delete API before undeploying function: {0}".format(str(ex)))
            message = "Skipping delete request from temp store for app: {0} as it hasn't been undeployed".format(
                self.function_name)
            if message not in str(ex):
                self.fail("Function delete succeeded even when function was in deployed state")
        self.undeploy_and_delete_function(body)
        try:
            # Try deleting a function which is already deleted
            self.delete_function(body)
        except Exception as ex:
            message = "App: {0} not deployed".format(self.function_name)
            if message not in str(ex):
                self.fail("Function delete succeeded even when function was in deployed state")

    def test_deploy_function_where_source_metadata_and_destination_buckets_dont_exist(self):
        # delete source, metadata and destination buckets
        for bucket in self.buckets:
            self.rest.delete_bucket(bucket.name)
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.BUCKET_OPS_ON_UPDATE, worker_count=3)
        try:
            self.rest.save_function(body['appname'], body)
            self.rest.deploy_function(body['appname'], body)
        except Exception as ex:
            if "Source bucket missing" not in str(ex):
                self.fail("Function save/deploy succeeded even when src/dst/metadata buckets doesn't exist")

    def test_deploy_function_where_source_and_metadata_buckets_are_same(self):
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size)
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.BUCKET_OPS_ON_UPDATE, worker_count=3)
        # set both src and metadata bucket as same
        body['depcfg']['metadata_bucket'] = self.src_bucket_name
        try:
            self.rest.save_function(body['appname'], body)
            # Try to deploy the function
            self.rest.deploy_function(body['appname'], body)
        except Exception as ex:
            if "Source bucket same as metadata bucket" not in str(ex):
                self.fail("Eventing function allowed both source and metadata bucket to be same")

    def test_eventing_with_memcached_buckets(self):
        # delete existing couchbase buckets which will be created as part of setup
        for bucket in self.buckets:
            self.rest.delete_bucket(bucket.name)
        # create memcached bucket with the same name
        bucket_params = self._create_bucket_params(server=self.server, size=self.bucket_size,
                                                   replicas=self.num_replicas)
        tasks = []
        for bucket in self.buckets:
            tasks.append(self.cluster.async_create_memcached_bucket(name=bucket.name,
                                                                    port=STANDARD_BUCKET_PORT + 1,
                                                                    bucket_params=bucket_params))
        for task in tasks:
            task.result()
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.BUCKET_OPS_ON_UPDATE, worker_count=3)
        try:
            self.rest.save_function(body['appname'], body)
            self.rest.deploy_function(body['appname'], body)
        except Exception as ex:
            if "Source bucket is memcached, should be either couchbase or ephemeral" not in str(ex):
                self.fail("Eventing function allowed both source and metadata bucket to be memcached buckets")

    def test_src_metadata_and_dst_bucket_flush_and_delete_when_eventing_is_processing_mutations(self):
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.BUCKET_OPS_WITH_DOC_TIMER)
        self.deploy_function(body)
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size)
        # flush source, metadata and destination buckets when eventing is processing_mutations
        for bucket in self.buckets:
            self.rest.flush_bucket(bucket.name)
        # delete source, metadata and destination buckets when eventing is processing_mutations
        for bucket in self.buckets:
                self.rest.delete_bucket(bucket.name)
        self.undeploy_and_delete_function(body)
        # check if all the eventing-consumers are cleaned up
        # Validation of any issues like panic will be taken care by teardown method
        self.assertTrue(self.check_if_eventing_consumers_are_cleaned_up(),
                        msg="eventing-consumer processes are not cleaned up even after undeploying the function")

    def test_undeploy_when_function_is_still_in_bootstrap_state(self):
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size)
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.BUCKET_OPS_ON_UPDATE, worker_count=3)
        self.deploy_function(body, wait_for_bootstrap=False)
        try:
            # Try undeploying the function when it is still bootstrapping
            self.undeploy_function(body)
        except Exception as ex:
            if "not bootstrapped, discarding request to undeploy it" not in str(ex):
                self.fail("Function undeploy succeeded even when function was in bootstrapping state")
        # Wait for eventing to catch up with all the create mutations and verify results
        self.wait_for_bootstrap_to_complete(body['appname'])
        self.verify_eventing_results(self.function_name, self.docs_per_day * 2016)
        self.undeploy_and_delete_function(body)

    def test_function_where_handler_code_takes_more_time_to_execute_than_execution_timeout(self):
        keys = ['customer123', 'customer1234', 'customer12345']
        url = 'couchbase://{ip}/{name}'.format(ip=self.master.ip, name=self.src_bucket_name)
        bucket = Bucket(url, username="cbadminbucket", password="password")
        for doc_id in keys:
            bucket.upsert(doc_id, {'name' : doc_id})
        # create a function which sleeps for 5 secs and set execution_timeout to 1s
        body = self.create_save_function_body(self.function_name, HANDLER_CODE_ERROR.EXECUTION_TIME_MORE_THAN_TIMEOUT,
                                              execution_timeout=1)
        # deploy the function
        self.deploy_function(body)
        # This is intentionally added so that we wait for some mutations to process and we decide none are processed
        self.sleep(60)
        # No docs should be present in dst_bucket as the all the function executions should have timed out
        self.verify_eventing_results(self.function_name, 0, skip_stats_validation=True)
        eventing_nodes = self.get_nodes_from_services_map(service_type="eventing", get_all_nodes=True)
        exec_timeout_count = 0
        for eventing_node in eventing_nodes:
            rest_conn = RestConnection(eventing_node)
            out = rest_conn.get_all_eventing_stats()
            # get sum of all timeout_count
            exec_timeout_count += out[0]["failure_stats"]["timeout_count"]
        # check whether all the function executions timed out and is equal to number of docs created
        if exec_timeout_count != len(keys):
            self.fail("Not all event executions timed out : Expected : {0} Actual : {1}".format(len(keys),
                                                                                                exec_timeout_count))
        self.undeploy_and_delete_function(body)

    def test_syntax_error(self):
        self.load(self.gens_load, buckets=self.src_bucket, flag=self.item_flag, verify_data=False,
                  batch_size=self.batch_size)
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.SYNTAX_ERROR)
        try:
            self.deploy_function(body, deployment_fail=True)
        except Exception as e:
            if "Unexpected end of input" not in str(e):
                self.fail("Deployment is expected to be failed but no message of failure")

    def test_read_binary_data_from_the_function(self):
        gen_load_binary = BlobGenerator('binary1000000', 'binary', self.value_size, start=1,
                                        end=2016 * self.docs_per_day + 1)
        gen_load_json = JsonDocGenerator('binary', op_type="create", end=2016 * self.docs_per_day)
        # load binary data on dst bucket and non json on src bucket with identical keys so that we can read them
        self.cluster.load_gen_docs(self.master, self.src_bucket_name, gen_load_json, self.buckets[0].kvs[1], "create",
                                   exp=0, flag=0, batch_size=1000)
        self.cluster.load_gen_docs(self.master, self.dst_bucket_name, gen_load_binary, self.buckets[0].kvs[1], "create",
                                   exp=0, flag=0, batch_size=1000)
        body = self.create_save_function_body(self.function_name, HANDLER_CODE.READ_BUCKET_OP_ON_DST)
        self.deploy_function(body)
        # wait for some time so that exception_count increases
        # This is because we can't read binary data from handler code
        self.sleep(60)
        stats = self.rest.get_all_eventing_stats()
        bucket_op_exception_count = stats[0]["failure_stats"]["bucket_op_exception_count"]
        self.undeploy_and_delete_function(body)
        log.info("stats : {0}".format(json.dumps(stats, sort_keys=True, indent=4)))
        if bucket_op_exception_count == 0:
            self.fail("Reading binary data succeeded from handler code")