import os
import sys
import glob
import h5py
import pickle
import stan
import optparse
# import threading
import warnings
import traceback
import arviz                           as az
import numpy                           as np
import matplotlib.pyplot               as plt
import lib.misc_functions              as misc
from   lib.create_diagnostic_plots     import create_diagnostic_plots
from   hashlib                         import md5
from multiprocessing import Queue, Process, cpu_count, Pool


#==============================================================================
def worker(inQueue, outQueue):

    """
    Defines the worker process of the parallelisation with multiprocessing.Queue
    and multiprocessing.Process.
    """
    for i, bin_list, runname, niter, nchain, adapt_delta, max_treedepth, verbose, save_chains, save_plots, fit_type in iter(inQueue.get, 'STOP'):

        status = run(i, bin_list, runname, niter, nchain, adapt_delta, max_treedepth, verbose, save_chains, save_plots, fit_type)

        outQueue.put(( status ))

#==============================================================================
def stan_cache(model_code, model_name=None, codefile=None, **kwargs):

    """Use just as you would `stan`"""
    code_hash = md5(model_code.encode('ascii')).hexdigest()
    if model_name is None:
        cache_fn = 'stan_model/cached-model-{}.pkl'.format(code_hash)
    else:
        cache_fn = 'stan_model/cached-{}-{}.pkl'.format(model_name, code_hash)
    try:
        raise Exception("don't use cache")
        sm = pickle.load(open(cache_fn, 'rb'))
    except:
        sm = stan.build(model_code)
        with open(cache_fn, 'wb') as f:
            pickle.dump(sm, f)
    else:
        print("Using cached StanModel for "+codefile)

    return sm
#==============================================================================
def run(i, bin_list, runname, niter, nchain, adapt_delta, max_treedepth,
        verbose=False, save_chains=False, save_plots=False, fit_type=None):

    idx = bin_list[i]
    stridx = str(idx)
    misc.printRUNNING(runname+" - Bin: "+stridx+" - Fit type: "+fit_type)

    try:

        # Defining the version of the code to use
        codefile, extrapars = misc.read_code(fit_type)

        # Defining output names and directories
        rootname         = runname+"-"+fit_type
        outdir           = "../results/"+rootname
        pdf_filename     = outdir+"/"+rootname+"_diagnostics_bin"+str(idx)+".pdf"
        summary_filename = outdir+"/"+rootname+"_Stan_summary_bin"+str(idx)+".txt"
        arviz_filename   = outdir+"/"+rootname+"_chains_bin"+str(idx)+".netcdf"
        sample_filename  = outdir+"/"+rootname+"_progress_bin"+str(idx)+".csv"
        outhdf5          = outdir+"/"+rootname+"_results_bin"+str(idx)+".hdf5"

        # Creating the basic structure with the data for Stan
        struct = h5py.File("../preproc_data/"+runname+".hdf5","r")
        data   = {'npix_obs':      np.array(struct['in/npix_obs']),
                  'ntemp':         np.array(struct['in/ntemp']),
                  'nvel':          np.array(struct['in/nvel']),
                  'npix_temp':     np.array(struct['in/npix_temp']),
                  'mask':          np.array(struct['in/mask']),
                  'nmask':         np.array(struct['in/nmask']),
                  'porder':        np.array(struct['in/porder']),
                  'spec_obs':      np.array(struct['in/spec_obs'][:,idx]),
                  'sigma_obs':     np.array(struct['in/sigma_obs'][:,idx]),
                  'templates':     np.array(struct['in/templates']),
                  'mean_template': np.array(struct['in/mean_template']),
                  'velscale':      np.array(struct['in/velscale']),
                  'xvel':          np.array(struct['in/xvel'])}

        # Adding any extra parameter needed for that particular fit_type
        for key, val in extrapars.items():
            data[key] = val

        # Running the model
        with open(codefile, 'r') as myfile:
           code = myfile.read()
        model   = stan.build(code,data=data)
        fit     = model.sample(num_samples=niter, num_chains=nchain)

        samples   = fit # Extracting parameter samples
        # diag_pars = fit.get_sampler_params()   # Getting sampler diagnostic params
        # If requested, saving sample chains
        if (save_chains == True):
           print("")
           print("# Saving chains in Arviz (NETCDF) format: "+arviz_filename)
           arviz_data = az.from_pystan(posterior=fit, observed_data=['mask','spec_obs','sigma_obs'])
           az.to_netcdf(arviz_data,arviz_filename)

        # Saving Stan's summary of main parameters on disk
        print("")
        print("# Saving Stan summary: "+summary_filename)
        unwanted = {'spec','conv_spec','poly','bestfit','a','losvd_'}
        # misc.save_stan_summary(fit, unwanted=unwanted, verbose=verbose, summary_filename=summary_filename)

        # Processing output and saving results
        print("")
        print("# Processing and saving results: "+outhdf5)
        misc.process_stan_output_hdp(struct,samples,outhdf5,stridx)

        # Creating diagnostic plots
        if (save_plots == True):
            if os.path.exists(pdf_filename):
              os.remove(pdf_filename)
            print("")
            # print("# Saving diagnostic plots: "+pdf_filename)
            # create_diagnostic_plots(idx, pdf_filename, fit, diag_pars, niter, nchain)

        # Removing progess files
        print("")
        print("# Deleting progress files")
        misc.delete_files(sample_filename,'csv')
        misc.delete_files(sample_filename,'png')

        # If we are here, we are DONE!
        struct.close()
        misc.printDONE(runname+" - Bin: "+stridx+" - Fit type: "+fit_type)

        return 'OK'

    except Exception:

        misc.printFAILED()
        traceback.print_exc()

        return 'ERROR'

#==============================================================================
if (__name__ == '__main__'):

    warnings.filterwarnings("ignore")

    print("===========================================")
    print("               BAYES-LOSVD                 ")
    print("                  (run)                    ")
    print("===========================================")
    print("")

    # Capturing the command line arguments
    parser = optparse.OptionParser(usage="%prog -f file")
    parser.add_option("-f", "--preproc_file",  dest="preproc_file",  type="string", default="",     help="Filename of the preprocessed file")
    parser.add_option("-i", "--niter",         dest="niter",         type="int",    default=500,    help="Number of iterations in stan")
    parser.add_option("-c", "--nchain",        dest="nchain",        type="int",    default=1,      help="Number of simultaneous chains to run")
    parser.add_option("-a", "--adapt_delta",   dest="adapt_delta",   type="float",  default=0.99,   help="Stan Adapt_delta")
    parser.add_option("-d", "--max_treedepth", dest="max_treedepth", type="int",    default=18,     help="Stan maximum tree depth")
    parser.add_option("-b", "--bin",           dest="bin",           type="string", default="all",  help="Bin ID for spectrum run [all,odd,even,bin_list]")
    parser.add_option("-n", "--njobs",         dest="njobs",         type="int",    default=1,      help="Number of jobs to lauch in parallel")
    parser.add_option("-v", "--verbose",       dest="verbose",       type="int",    default=0,      help="Printing Stan summary for each fit (Default: 0/False)")
    parser.add_option("-s", "--save_chains",   dest="save_chains",   type="int",    default=0,      help="Saving chains for each fit (Default: 0/False)")
    parser.add_option("-p", "--save_plots",    dest="save_plots",    type="int",    default=0,      help="Saving diagnistic plots (Default: 0/False)")
    parser.add_option("-t", "--fit_type",      dest="fit_type",      type="string", default="SP",   help="Defining the type of fit (Default: S0 [Pure simplex])")
    parser.add_option("-m", "--mask_bin",      dest="mask_bin",      type="string", default="None", help="Bin ID to mask [Default: None]")
    parser.add_option("-x", "--restart",       dest="restart",       type="int",    default=0,      help="Restart run [Default: 0/False]")

    (options, args) = parser.parse_args()
    preproc_file    = options.preproc_file
    niter           = options.niter
    nchain          = options.nchain
    adapt_delta     = options.adapt_delta
    max_treedepth   = options.max_treedepth
    bin             = options.bin
    njobs           = options.njobs
    verbose         = options.verbose
    save_chains     = options.save_chains
    save_plots      = options.save_plots
    fit_type        = options.fit_type
    mask_bin        = options.mask_bin
    restart         = options.restart

    if (verbose == 0):
        verbose = False
    else:
        verbose = True

    if (save_chains == 0):
        save_chains = False
    else:
        save_chains = True

    if (save_plots == 0):
        save_plots = False
    else:
        save_plots = True

    if (restart == 0):
        restart = False
    else:
        restart = True

    # Checking the file exists
    if not os.path.exists(preproc_file):
       misc.printFAILED(preproc_file+" does not exist.")
       sys.exit()

    # Checking fit_type is a valid one
    misc.check_codes(fit_type)

    # Defining rootnames for output files
    tmpname = os.path.basename(preproc_file)
    runname = os.path.splitext(tmpname)[0]
    outdir  = "../results/"+runname+"-"+fit_type

    if not os.path.exists("../results"):
        os.mkdir("../results")
    if not os.path.exists(outdir):
        os.mkdir(outdir)

    # Loading input information from the preproc file
    f     = h5py.File(preproc_file,'r')
    nbins = np.array(f['in/nbins'])
    f.close()

    # Defining the list of bins to be analysed
    bin_list, nbins = misc.create_bins_list(bin, nbins, mask_bin, outdir, restart)

    # Managing the work PARALLEL or SERIAL accordingly
    if njobs*nchain > cpu_count():
        misc.printWARNING("The chosen number of NJOBS and NCHAIN seems to be larger than the number of CPUs in the system!")

    ### This doesn't work as pystan uses async/paralleisation itself and Pool processes
    ### are not allowed to span further subprocesses
    # jobs=[]
    # # Fill the queue
    # for i in range(nbins):
    #     jobs.append( ( i, bin_list, runname, niter, nchain, adapt_delta,
    #                    max_treedepth, verbose, save_chains, save_plots, fit_type) )
    # with Pool(njobs) as p:
    #     run_tmp=p.starmap(run,jobs)


    assert njobs == 1
    run_tmp=[]
    # Fill the queue
    for i in range(nbins):
        out = run(i, bin_list, runname, niter, nchain, adapt_delta,
                       max_treedepth, verbose, save_chains, save_plots, fit_type)
        run_tmp.append(out)

    # Pack all results into a single file if everything went OK
    if 'ERROR' not in run_tmp:
       print("")
       print("# Packing all results into a single HDF5 file.")
       misc.pack_results(runname+"-"+fit_type)

