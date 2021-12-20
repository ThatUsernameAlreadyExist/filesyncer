This tutorial shows quickly how to use tinydav. 
HTTPClient

To instantiate the HTTPClient you have to give at the host (either IP address or name) to contact. Optionally you can pass a specific port number. The default port number is 80. 
from tinydav import HTTPClient

httpclient = HTTPClient("www.google.de", 8080)

response = httpclient.get("/")

if response == 200:
    print response.statusline
    # 'HTTP/1.1 200 OK'
    print response.headers["content-type"]
    # 'text/html; charset=ISO-8859-1'
    print response.content
    # '<!doctype html><html><head><meta http-equiv="cont ...

Above we sent a GET request to the server's root. Each HTTP request method can be fired by an object method with the same name (just lowercase). As argument you have to give a string with the path of the resource. Additionally you can add custom headers to the request: 
headers = {
    "X-my-header": "hello"
}
response = httpclient.get("/", headers=headers) 

If you have query parameters to be added to the URL, just give the query argument: 
query = {
    "q": "python",
    "hl": "de"
}
response = httpclient.get("/search", query=query)

This results in a HTTP request as the following: 
GET /search?q=python&hl=de HTTP/1.1

You see, the elements of the query dict are appended to the URL after a question mark. The added values will be urlencoded. 

As the response object is a subclass of int you can check the HTTP status code directly by comparing to an int (see example above). 

The response object has three attributes of interest. statusline show's the complete returned HTTP status line. headers is a dictionary containing all the returned headers. The header names are all lowercase. content contains the content of the response body. 

All other methods work like the above example, but they may have additional arguments. 

E.g. the post method takes an optional content argument: 
response = httpclient.post("/somewhere", "I'm the content", headers=headers, query=query)

The content may either be a string or a file descriptor (or anything that has a read method) or a dictionary. Giving a dictionary will cause the POST request to be a application/x-www-form-urlencoded request. Setting the as_multipart parameter to True, the request will be sent as multipart/form-data instead. 
content = {
    "foo": "bar",
    "a_file": open("/tmp/test.txt"),
}
response = httpclient.post("/somewhere", content, as_multipart=True)

The put method takes an additional fileobject (or anything that has a read method). 
with open("myfile", "rb") as fd:
    response = httpclient.put("/somewhere", fd, headers=headers, query=query)

The trace method takes no query argument at all, but may take a maxforwards argument and/or a via argument. 
response = httpclient.trace("/", maxforwards=5)

For the via argument you may want to check RFC 2616. 

For more explanation explore the documentation.