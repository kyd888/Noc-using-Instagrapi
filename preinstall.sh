pip install --upgrade pip

# Install numpy first
pip install numpy==1.23.5

# Install remaining dependencies using the legacy resolver
pip install --use-deprecated=legacy-resolver -r requirements.txt
