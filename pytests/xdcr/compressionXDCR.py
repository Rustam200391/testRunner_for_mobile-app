from xdcrnewbasetests import XDCRNewBaseTest, NodeHelper
from remote.remote_util import RemoteMachineShellConnection, RestConnection
from couchbase_helper.documentgenerator import BlobGenerator
import json

class compression(XDCRNewBaseTest):
    def setUp(self):
        super(compression, self).setUp()
        self.src_cluster = self.get_cb_cluster_by_name('C1')
        self.src_master = self.src_cluster.get_master_node()
        self.dest_cluster = self.get_cb_cluster_by_name('C2')
        self.dest_master = self.dest_cluster.get_master_node()

    def tearDown(self):
        super(compression, self).tearDown()

    def _set_compression_type(self, cluster, bucket_name, compression_type="None"):
        repls = cluster.get_remote_clusters()[0].get_replications()
        for repl in repls:
            if bucket_name in str(repl):
                repl_id = repl.get_repl_id()
        shell = RemoteMachineShellConnection(cluster.get_master_node())
        repl_id = str(repl_id).replace('/','%2F')
        base_url = "http://" + cluster.get_master_node().ip + ":8091/settings/replications/" + repl_id
        command = "curl -X POST -u Administrator:password " + base_url + " -d compressionType=" + str(compression_type)
        output, error = shell.execute_command(command)
        shell.log_command_output(output, error)
        shell.disconnect()
        return output, error

    def _verify_compression(self, cluster, compr_bucket_name="", uncompr_bucket_name="", compression_type="None"):
        repls = cluster.get_remote_clusters()[0].get_replications()
        for repl in repls:
            if compr_bucket_name in str(repl):
                compr_repl_id = repl.get_repl_id()
            elif uncompr_bucket_name in str(repl):
                uncompr_repl_id = repl.get_repl_id()

        compr_repl_id = str(compr_repl_id).replace('/', '%2F')
        uncompr_repl_id = str(uncompr_repl_id).replace('/', '%2F')

        base_url = "http://" + cluster.get_master_node().ip + ":8091/settings/replications/" + compr_repl_id
        shell = RemoteMachineShellConnection(cluster.get_master_node())
        command = "curl -u Administrator:password " + base_url
        output, error = shell.execute_command(command)
        shell.log_command_output(output, error)
        self.assertTrue('"compressionType":"Snappy"' in output[0],
                        "Compression Type for replication " + compr_repl_id + " is not Snappy")
        self.log.info("Compression Type for replication " + compr_repl_id + " is Snappy")

        base_url = "http://" + cluster.get_master_node().ip + ":8091/pools/default/buckets/" + compr_bucket_name + \
                   "/stats/replications%2F" + compr_repl_id + "%2Fdata_replicated"
        command = "curl -u Administrator:password " + base_url
        output, error = shell.execute_command(command)
        shell.log_command_output(output, error)
        output = json.loads(output[0])
        compressed_data_replicated = output["nodeStats"]["{0}:8091".format(cluster.get_master_node().ip)][-1]
        self.log.info("Compressed data for replication {0} is {1}".format(compr_repl_id, compressed_data_replicated))

        base_url = "http://" + cluster.get_master_node().ip + ":8091/pools/default/buckets/" + uncompr_bucket_name + \
                   "/stats/replications%2F" + uncompr_repl_id + "%2Fdata_replicated"
        command = "curl -u Administrator:password " + base_url
        output, error = shell.execute_command(command)
        shell.log_command_output(output, error)
        output = json.loads(output[0])
        uncompressed_data_replicated = output["nodeStats"]['{0}:8091'.format(cluster.get_master_node().ip)][-1]
        self.log.info("Uncompressed data for replication {0} is {1}".format(uncompr_repl_id, uncompressed_data_replicated))

        self.assertTrue(uncompressed_data_replicated > compressed_data_replicated,
                        "Compression did not work as expected")
        self.log.info("Compression worked as expected")

        shell.disconnect()

    def test_compression_with_unixdcr_incr_load(self):
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.perform_update_delete()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_unixdcr_backfill_load(self):
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)

        self.src_cluster.pause_all_replications()

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.src_cluster.resume_all_replications()

        self.perform_update_delete()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_bixdcr_incr_load(self):
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)
        self._set_compression_type(self.dest_cluster, "standard_bucket_1", compression_type)

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)
        gen_create = BlobGenerator('comprTwo-', 'comprTwo-', self._value_size, end=self._num_items)
        self.dest_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.perform_update_delete()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self._verify_compression(cluster=self.dest_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_bixdcr_backfill_load(self):
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)
        self._set_compression_type(self.dest_cluster, "standard_bucket_1", compression_type)

        self.src_cluster.pause_all_replications()
        self.dest_cluster.pause_all_replications()

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)
        gen_create = BlobGenerator('comprTwo-', 'comprTwo-', self._value_size, end=self._num_items)
        self.dest_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.src_cluster.resume_all_replications()
        self.dest_cluster.resume_all_replications()

        self.perform_update_delete()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self._verify_compression(cluster=self.dest_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_pause_resume(self):
        repeat = self._input.param("repeat", 5)
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)
        gen_create = BlobGenerator('comprTwo-', 'comprTwo-', self._value_size, end=self._num_items)
        self.dest_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.async_perform_update_delete()

        for i in range(0, repeat):
            self.src_cluster.pause_all_replications()
            self.sleep(30)
            self.src_cluster.resume_all_replications()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_optimistic_threshold_change(self):
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)

        src_conn = RestConnection(self.src_cluster.get_master_node())
        src_conn.set_xdcr_param('standard_bucket_1', 'standard_bucket_1', 'optimisticReplicationThreshold',
                                self._optimistic_threshold)
        src_conn.set_xdcr_param('standard_bucket_2', 'standard_bucket_2', 'optimisticReplicationThreshold',
                                self._optimistic_threshold)

        self.src_cluster.pause_all_replications()

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)
        gen_create = BlobGenerator('comprTwo-', 'comprTwo-', self._value_size, end=self._num_items)
        self.dest_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.src_cluster.resume_all_replications()

        self.perform_update_delete()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_advanced_settings(self):
        batch_count = self._input.param("batch_count", 10)
        batch_size = self._input.param("batch_size", 2048)
        source_nozzle = self._input.param("source_nozzle", 2)
        target_nozzle = self._input.param("target_nozzle", 2)

        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        self._set_compression_type(self.src_cluster, "standard_bucket_1", compression_type)

        src_conn = RestConnection(self.src_cluster.get_master_node())
        src_conn.set_xdcr_param('standard_bucket_1', 'standard_bucket_1', 'workerBatchSize', batch_count)
        src_conn.set_xdcr_param('standard_bucket_1', 'standard_bucket_1', 'docBatchSizeKb', batch_size)
        src_conn.set_xdcr_param('standard_bucket_1', 'standard_bucket_1', 'sourceNozzlePerNode', source_nozzle)
        src_conn.set_xdcr_param('standard_bucket_1', 'standard_bucket_1', 'targetNozzlePerNode', target_nozzle)
        src_conn.set_xdcr_param('standard_bucket_2', 'standard_bucket_1', 'workerBatchSize', batch_count)
        src_conn.set_xdcr_param('standard_bucket_2', 'standard_bucket_1', 'docBatchSizeKb', batch_size)
        src_conn.set_xdcr_param('standard_bucket_2', 'standard_bucket_1', 'sourceNozzlePerNode', source_nozzle)
        src_conn.set_xdcr_param('standard_bucket_2', 'standard_bucket_1', 'targetNozzlePerNode', target_nozzle)

        self.src_cluster.pause_all_replications()

        gen_create = BlobGenerator('comprOne-', 'comprOne-', self._value_size, end=self._num_items)
        self.src_cluster.load_all_buckets_from_generator(kv_gen=gen_create)
        gen_create = BlobGenerator('comprTwo-', 'comprTwo-', self._value_size, end=self._num_items)
        self.dest_cluster.load_all_buckets_from_generator(kv_gen=gen_create)

        self.src_cluster.resume_all_replications()

        self.perform_update_delete()

        self._verify_compression(cluster=self.src_cluster,
                                 compr_bucket_name="standard_bucket_1",
                                 uncompr_bucket_name="standard_bucket_2",
                                 compression_type=compression_type)
        self.verify_results()

    def test_compression_with_capi(self):
        self.setup_xdcr()
        self.sleep(60)
        compression_type = self._input.param("compression_type", "Snappy")
        output, error = self._set_compression_type(self.src_cluster, "default", compression_type)
        self.assertTrue("The value can not be specified for CAPI replication" in output[0], "Compression enabled for CAPI")
        self.log.info("Compression not enabled for CAPI as expected")