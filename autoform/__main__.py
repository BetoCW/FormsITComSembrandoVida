import sys

if len(sys.argv) > 1:
    from .batch import main
    main()
else:
    from .gui import main
    main()
