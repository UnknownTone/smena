import sys

if len(sys.argv) > 2 and sys.argv[1] == "--run-script":      # сборка: скрипты подготовки и корпуса
    from smena.runtime import run_script
    run_script(sys.argv[2:])
elif len(sys.argv) > 1 and sys.argv[1] == "--selftest":      # проверка сборки без окна
    from smena.selftest import main
    sys.exit(main())
else:
    if sys.platform == "win32" or getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()
    from smena.app import main
    main()
