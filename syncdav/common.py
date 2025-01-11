import threading


class AtomicInteger(object):
    def __init__(self, initial=0):
        self.value = initial
        self._lock = threading.Lock()

    def inc(self, delta=1):
        with self._lock:
            self.value += delta
            return self.value

    def dec(self, delta=1):
        with self._lock:
            self.value -= delta
            return self.value

    def get(self):
        with self._lock:
            return self.value

    def set(self, newValue):
        with self._lock:
            self.value = newValue
            return self.value


class DummyLock:
    def __enter__(self):
        pass

    def __exit__(self ,type, value, traceback):
        pass


class PathOperations:
    @staticmethod
    def getPathLastElement(path):
        lastElement = path
        items = PathOperations.splitPath(path)
        if items:
            lastElement = items.pop()
        return lastElement
        
    @staticmethod    
    def splitPath(path):
        items = path.split('\\')
        fixedItems = []
        for i in items:
            if i != '':
                subItems = i.split('/')
                for j in subItems:
                     if j != '':
                        fixedItems.append(j)
        return fixedItems
        
    @staticmethod    
    def comparePath(firstPath, secondPath):
        return PathOperations.splitPath(firstPath) == PathOperations.splitPath(secondPath)
        
    @staticmethod    
    def isSubPath(firstPath, secondPath):
        firstElements = PathOperations.splitPath(firstPath)
        secondElements = PathOperations.splitPath(secondPath)
        subPath = False
        if len(firstElements) < len(secondElements):
            subPath = True
            for index, el in enumerate(firstElements):
                if secondElements[index] != el:
                    subPath = False
                    break;
                    
        return subPath
        
        