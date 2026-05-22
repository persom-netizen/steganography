from app import app
p='uploads/uploaded_cover_9e4858f71ddd4b8db3e19a52f10b357f.png'
with app.test_client() as c:
    with open(p,'rb') as f:
        data={
            'simulation_id':'1',
            'edge_threshold_low':'0.3',
            'edge_threshold_high':'0.7',
            'bit_depth':'3'
        }
        data['image']=(f, 'file.png')
        resp = c.post('/api/upload-image', data=data, content_type='multipart/form-data')
        print('STATUS', resp.status_code)
        print(resp.get_data(as_text=True)[:2000])
