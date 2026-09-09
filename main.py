import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from mora_cutter.app import main

    main()
