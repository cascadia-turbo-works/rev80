import vibechecker as vc
from path import Path
from datetime import datetime
import h5py, glob
import sys

cont = input('This script will convert legacy pkl files into h5 format. Checkout vibegui:rc0.2 to use. Continue? (y,N)')
if not cont or not cont[0].lower() == 'y':
    sys.exit(0)

vd = vc.DataCollector()
names = {'raw_data': 'data',
         'raw_unit': 'unit'}

def recover_data(dataset, label:str, ts:datetime):
    # load pickle
    vd.load_data(dataset.with_suffix('.pkl'))

    with h5py.File(dataset.with_suffix('.h5'), 'w') as f:
        for key in vd.sample.__dataclass_fields__.keys():
            data = vd.sample.__getattribute__(key)
            key = names.get(key, key)
            if key == 'integration':
                continue
            elif key == 'status':
                data = 'OKAY'
            elif key == 'timestamp':
                f.create_dataset('rel_time', data=data)
                data = str(ts)
            
            try:
                f.create_dataset(key, data=data)
            except TypeError as e:
                print(f'H5 failed to save {key} = {data} ({type(data)})')
                raise

        f.create_dataset('label', data=label)

    print(f'Saved H5 for {dataset}')

# Recover all pkls to h5.
vd = vc.DataCollector()

datasets = list(map(Path,map(lambda s: s[:-4],glob.glob('DEVDATA/*.pkl'))))

for dataset in datasets:
    file = dataset.basename().split('_')

    if not file:
        continue
    if len(file) == 1:
        label = file[0]
        ts = datetime.now() # no timestamp, add current
    else:
        label = '_'.join(file[:-2])
        timestamp_str = '_'.join(file[-2:])
        try:
            ts =  datetime.fromisoformat(timestamp_str)
        except ValueError as e:
            ts = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
 
    print(label, ts)
    
    try:
        recover_data(dataset, label, ts)
    except Exception as e:
        print(e)
